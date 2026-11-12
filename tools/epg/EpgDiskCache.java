package com.github.tvbox.osc.util;

import com.github.tvbox.osc.base.App;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.security.MessageDigest;
import java.util.HashMap;

/**
 * [观影听涛] EPG 本地库（最小可用版，2026-11-12）
 *
 * 借鉴超级直播「本地 epg.db + TTL + 失败保留旧库」的设计思想，但不引入 SQLite：
 * 直接缓存 DIYP 接口的原始响应体，命中后复用上游原有解析逻辑，零侵入。
 *
 * 为什么这么做：
 *  - 上游 hsEpg 是纯内存 Hashtable，进程一重启就全丢，每次打开都要重新打公益接口；
 *  - 若在 m3u 头写 x-tvg-url，静态 gz 会忽略 query 返回 922KB 全量、每切台白下（已踩过坑）；
 *  - 按台缓存响应体最小、最省流量，也顺带让频道列表能显示「正在播什么」。
 *
 * 约束：不新增依赖、不碰网络层、缓存失败一律静默降级，绝不影响播放。
 */
public class EpgDiskCache {

    private static final long TTL_MS = 6L * 60L * 60L * 1000L;      // 节目单有效期 6 小时
    private static final long TITLE_MEM_MS = 5L * 60L * 1000L;       // 列表标题内存缓存 5 分钟
    private static final String CURRENT_SUFFIX = "#current";

    private static final HashMap<String, String> titleCache = new HashMap<String, String>();
    private static final HashMap<String, Long> titleCacheAt = new HashMap<String, Long>();

    private static File dir() {
        File d = new File(App.getInstance().getFilesDir(), "taoying_epg");
        if (!d.exists()) {
            d.mkdirs();
        }
        return d;
    }

    private static String md5(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] b = md.digest(s.getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < b.length; i++) {
                sb.append(String.format("%02x", b[i] & 0xff));
            }
            return sb.toString();
        } catch (Exception e) {
            return Integer.toHexString(s.hashCode());
        }
    }

    private static File fileFor(String key) {
        return new File(dir(), md5(key) + ".dat");
    }

    /**
     * @param allowStale true = 忽略 TTL 读旧库（接口失败 / 缓存过期但还没刷新成功时用）
     */
    public static String get(String key, boolean allowStale) {
        if (key == null) {
            return null;
        }
        File f = fileFor(key);
        if (!f.exists() || f.length() == 0) {
            return null;
        }
        if (!allowStale && System.currentTimeMillis() - f.lastModified() > TTL_MS) {
            return null;
        }
        BufferedReader br = null;
        try {
            br = new BufferedReader(new InputStreamReader(new FileInputStream(f), "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line);
            }
            return sb.length() == 0 ? null : sb.toString();
        } catch (Exception e) {
            return null;
        } finally {
            if (br != null) {
                try {
                    br.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    /** 原子写：先写 .tmp 再改名，避免中途退出留下半截 JSON */
    public static void put(String key, String body) {
        if (key == null || body == null || body.length() < 2) {
            return;
        }
        File f = fileFor(key);
        File tmp = new File(f.getParentFile(), f.getName() + ".tmp");
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(tmp);
            out.write(body.getBytes("UTF-8"));
            out.flush();
            out.close();
            out = null;
            if (f.exists()) {
                f.delete();
            }
            tmp.renameTo(f);
        } catch (Exception e) {
            if (tmp.exists()) {
                tmp.delete();
            }
        } finally {
            if (out != null) {
                try {
                    out.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    /**
     * 台名归一化：上游拿 EPG 时会把 "CCTV-11" 规范成 "CCTV11"，而频道列表显示的是
     * 原始台名 "CCTV-11"。两边直接用各自的名字当 key 会对不上（v4 实测根因），
     * 所以写入/读取都同时兼容「原名」和「去符号小写名」。
     */
    private static String norm(String s) {
        if (s == null) {
            return "";
        }
        return s.replaceAll("[^a-zA-Z0-9\\u4e00-\\u9fa5]", "").toLowerCase(java.util.Locale.ROOT);
    }

    /** 每次成功拿到某台节目单时，额外写固定 key 供频道列表读取（原名 + 归一化别名各一份） */
    public static void putCurrent(String channelName, String body) {
        if (channelName == null) {
            return;
        }
        put(channelName + CURRENT_SUFFIX, body);
        put(norm(channelName) + CURRENT_SUFFIX, body);
        // 频道列表可能早于 EPG 响应绑定过一次并缓存了 null（5 分钟内存缓存）；
        // 把原名与归一化别名的旧结果一并清掉，否则同一进程内列表 5 分钟都不刷新（v5 实测）
        String n = norm(channelName);
        java.util.Iterator<String> it = titleCacheAt.keySet().iterator();
        while (it.hasNext()) {
            String k = it.next();
            if (norm(k).equals(n)) {
                it.remove();
                titleCache.remove(k);
            }
        }
    }

    /** 频道列表用：返回当前时段节目名；没有缓存或解析不出来返回 null */
    public static String currentProgram(String channelName) {
        if (channelName == null || channelName.trim().length() == 0) {
            return null;
        }
        long now = System.currentTimeMillis();
        Long at = titleCacheAt.get(channelName);
        if (at != null && now - at.longValue() < TITLE_MEM_MS) {
            return titleCache.get(channelName);
        }
        String title = null;
        String rawKey = channelName + CURRENT_SUFFIX;
        String normKey = norm(channelName) + CURRENT_SUFFIX;
        String body = get(rawKey, false);
        if (body == null && !normKey.equals(rawKey)) {
            body = get(normKey, false);                       // EPG 侧用的是规范化台名
        }
        if (body == null) {
            body = get(rawKey, true);                         // 过期也先显示旧节目单
        }
        if (body == null && !normKey.equals(rawKey)) {
            body = get(normKey, true);
        }
        if (body != null && body.trim().startsWith("{")) {
            try {
                JSONObject obj = new JSONObject(body);
                JSONArray arr = obj.optJSONArray("epg_data");
                if (arr != null) {
                    java.util.Calendar cal = java.util.Calendar.getInstance();
                    int hm = cal.get(java.util.Calendar.HOUR_OF_DAY) * 100
                            + cal.get(java.util.Calendar.MINUTE);
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject p = arr.optJSONObject(i);
                        if (p == null) {
                            continue;
                        }
                        int s = hmOf(p.optString("start", ""));
                        int e = hmOf(p.optString("end", ""));
                        if (s < 0 || e < 0) {
                            continue;
                        }
                        if (e <= s) {
                            e += 2400;                       // 跨零点节目
                        }
                        int cur = hm < s ? hm + 2400 : hm;
                        if (cur >= s && cur < e) {
                            title = p.optString("title", "");
                            break;
                        }
                    }
                }
            } catch (Exception e) {
                title = null;
            }
        }
        if (title != null && title.length() == 0) {
            title = null;
        }
        titleCache.put(channelName, title);
        titleCacheAt.put(channelName, Long.valueOf(now));
        return title;
    }

    private static int hmOf(String hhmm) {
        if (hhmm == null) {
            return -1;
        }
        String[] p = hhmm.split(":");
        if (p.length < 2) {
            return -1;
        }
        try {
            return Integer.parseInt(p[0].trim()) * 100 + Integer.parseInt(p[1].trim());
        } catch (Exception e) {
            return -1;
        }
    }
}
