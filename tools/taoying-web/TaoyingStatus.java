package com.github.tvbox.osc.util;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import com.orhanobut.hawk.Hawk;

import org.json.JSONObject;

/**
 * [观影听涛] 手机端状态面板 / 远程配置 的数据来源。
 *
 * 用途：手机在同一个局域网里打开 http://盒子IP:9978/ ，直接看到电视当前在用什么源、
 * 什么画面比例，并且可以改完一键重启生效 —— 不用再拿遥控器在电视上敲网址。
 *
 * 设备类型判断（isTv）也为后续「盒子版 / 手机版 UI 分叉」留好入口。
 */
public final class TaoyingStatus {

    private TaoyingStatus() {
    }

    /**
     * 电视盒子判断：有 Leanback（电视专用桌面）且没有触摸屏。
     * 只看 Leanback 会把「带触摸的电视」误判成盒子，所以两个条件都要。
     */
    public static boolean isTv(Context ctx) {
        if (ctx == null) return false;
        try {
            PackageManager pm = ctx.getPackageManager();
            boolean leanback = pm.hasSystemFeature(PackageManager.FEATURE_LEANBACK)
                    || pm.hasSystemFeature("android.hardware.type.television");
            boolean touch = pm.hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN);
            return leanback && !touch;
        } catch (Throwable t) {
            return false;
        }
    }

    public static String deviceName(Context ctx) {
        return isTv(ctx) ? "电视盒子" : "手机";
    }

    /** 画面比例枚举名（与 VideoView.SCREEN_SCALE_* 对应） */
    public static String scaleName(int s) {
        switch (s) {
            case 1: return "16:9";
            case 2: return "4:3";
            case 3: return "填充";
            case 4: return "原始";
            case 5: return "裁剪";
            default: return "默认";
        }
    }

    public static String playerName(int pl) {
        if (pl == 1) return "IJK";
        if (pl == 2) return "EXO";
        return "系统";
    }

    /** 状态汇总，给手机端页面用 */
    public static String json(Context ctx) {
        if (ctx == null) {
            return "{\"error\":\"no context\"}";
        }
        JSONObject o = new JSONObject();
        try {
            String ver = "";
            try {
                ver = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0).versionName;
            } catch (Throwable ignore) {
            }
            int scale = Hawk.get(HawkConfig.LIVE_PLAY_SCALE, 0);
            int pl = Hawk.get(HawkConfig.LIVE_PLAY_TYPE, 2);
            o.put("app", "观影听涛");
            o.put("version", ver == null ? "" : ver);
            o.put("device", deviceName(ctx));
            o.put("sdk", Build.VERSION.SDK_INT);
            o.put("apiUrl", Hawk.get(HawkConfig.API_URL, ""));
            o.put("liveUrl", Hawk.get(HawkConfig.LIVE_API_URL, ""));
            o.put("scale", scaleName(scale));
            o.put("scaleValue", scale);
            o.put("player", playerName(pl));
            o.put("playerValue", pl);
            long last = Hawk.get("taoying_site_health_last", 0L);
            o.put("siteHealthAt", last);
        } catch (Throwable t) {
            // 拼 JSON 出错也要返回合法串，页面才不会白屏
        }
        return o.toString();
    }

    /** 白名单配置写入。只认这 4 个键，别的直接拒绝，避免被当成通用写接口。 */
    public static boolean set(String k, String v) {
        if (k == null || v == null) return false;
        try {
            if ("apiUrl".equals(k)) {
                Hawk.put(HawkConfig.API_URL, v.trim());
                return true;
            }
            if ("liveUrl".equals(k)) {
                Hawk.put(HawkConfig.LIVE_API_URL, v.trim());
                return true;
            }
            if ("scale".equals(k)) {
                Hawk.put(HawkConfig.LIVE_PLAY_SCALE, Integer.parseInt(v.trim()));
                return true;
            }
            if ("player".equals(k)) {
                Hawk.put(HawkConfig.LIVE_PLAY_TYPE, Integer.parseInt(v.trim()));
                return true;
            }
        } catch (Throwable t) {
            return false;
        }
        return false;
    }

    /**
     * 重启自身：先挂一个 600ms 后的启动 Intent，再延迟 350ms 杀进程。
     * 延迟是必要的 —— 否则 HTTP 响应还没写完进程就没了，手机端会显示「请求失败」。
     */
    public static void reboot(Context ctx) {
        try {
            Intent i = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
            if (i == null) return;
            int flags = Build.VERSION.SDK_INT >= 23
                    ? PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
                    : PendingIntent.FLAG_UPDATE_CURRENT;
            PendingIntent pi = PendingIntent.getActivity(ctx, 0, i, flags);
            AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
            if (am != null) {
                am.setExact(AlarmManager.RTC, System.currentTimeMillis() + 600, pi);
            }
            new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        Thread.sleep(350);
                    } catch (Throwable ignored) {
                    }
                    System.exit(0);
                }
            }, "ty-reboot").start();
        } catch (Throwable t) {
            // 某些盒子禁了 AlarmManager，退化成杀进程由用户手动打开
            System.exit(0);
        }
    }
}
