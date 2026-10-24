package com.github.tvbox.osc.util.health;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import com.github.catvod.crawler.Spider;
import com.github.tvbox.osc.api.ApiConfig;
import com.github.tvbox.osc.bean.SourceBean;
import com.orhanobut.hawk.Hawk;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * [涛影] 点播站点自检
 *
 * 目的：不用人工逐个点，App 自己把每个点播源真实加载一遍，输出哪些能用、哪些已死。
 * 判定方式与用户点开某个站点完全一致：getCSP(bean).homeContent(false)
 *
 * 结果写到外部私有目录，可用 adb 直接拉取：
 *   adb pull /sdcard/Android/data/<包名>/files/site-health.json
 *
 * 退出方式：
 *   Hawk.put("taoying_site_health_off", true)   // 永久关闭
 *   Hawk.put("taoying_site_health_days", 0)     // 每次启动都跑
 */
public final class SiteHealthChecker {

    public static final String FILE_NAME  = "site-health.json";
    public static final String K_LAST_RUN = "taoying_site_health_last";
    public static final String K_OFF      = "taoying_site_health_off";
    public static final String K_DAYS     = "taoying_site_health_days";

    /** 单个站点最长等待（秒） */
    private static final int PER_SITE_TIMEOUT = 10;
    /** 同时探测几个站点（太高容易互相干扰 jar 加载） */
    private static final int WORKERS = 3;
    /** 默认每几天自动跑一次 */
    private static final int DEFAULT_DAYS = 3;
    /** 启动后延迟多久开始，避开首屏加载 */
    private static final long START_DELAY_MS = 8000L;

    private SiteHealthChecker() {
    }

    public static void schedule(final Context ctx) {
        if (ctx == null) return;
        if (Hawk.get(K_OFF, false)) return;
        if (!shouldRun()) return;
        new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
            @Override
            public void run() {
                new Thread(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            run(ctx.getApplicationContext());
                        } catch (Throwable ignored) {
                        }
                    }
                }, "ty-site-health").start();
            }
        }, START_DELAY_MS);
    }

    private static boolean shouldRun() {
        try {
            long last = Hawk.get(K_LAST_RUN, 0L);
            if (last <= 0) return true;
            int days = Hawk.get(K_DAYS, DEFAULT_DAYS);
            if (days <= 0) return true;
            return System.currentTimeMillis() - last > (long) days * 86400000L;
        } catch (Throwable t) {
            return false;
        }
    }

    private static void run(Context ctx) {
        List<SourceBean> all = ApiConfig.get().getSourceBeanList();
        if (all == null || all.isEmpty()) return;

        List<SourceBean> targets = new ArrayList<>();
        for (SourceBean b : all) {
            if (b == null) continue;
            if (b.getType() != 3) continue;              // 只要点播（type=3）
            if (b.getApi() == null || b.getApi().isEmpty()) continue;
            targets.add(b);
        }
        if (targets.isEmpty()) return;

        final int total = targets.size();
        final AtomicInteger okCount = new AtomicInteger(0);
        final Context appCtx = ctx;

        // 全局总时限：站点越多给的时间越多，但封顶 8 分钟，避免盒子一直后台跑
        long budget = Math.min(480L, Math.max(90L, total * 4L));

        List<Callable<String>> tasks = new ArrayList<>();
        for (final SourceBean bean : targets) {
            tasks.add(new Callable<String>() {
                @Override
                public String call() {
                    return checkOne(bean);
                }
            });
        }

        ExecutorService pool = Executors.newFixedThreadPool(WORKERS);
        List<Future<String>> futures;
        try {
            futures = pool.invokeAll(tasks, budget, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            pool.shutdownNow();
            futures = new ArrayList<>();
        }
        pool.shutdownNow();

        List<String> lines = new ArrayList<>();
        for (int i = 0; i < targets.size(); i++) {
            SourceBean bean = targets.get(i);
            String verdict = "fail";
            String detail = "未执行";
            Future<String> f = i < futures.size() ? futures.get(i) : null;
            try {
                if (f == null) {
                    detail = "未执行";
                } else if (f.isCancelled()) {
                    detail = "总时限内未完成";
                } else {
                    String r = f.get(1, TimeUnit.SECONDS);
                    if (r == null) {
                        detail = "空返回";
                    } else if (r.startsWith("OK")) {
                        verdict = "ok";
                        okCount.incrementAndGet();
                        detail = r.substring(3);
                    } else {
                        detail = r.substring(3);
                    }
                }
            } catch (Exception e) {
                detail = e.getClass().getSimpleName();
            }
            lines.add(String.format(Locale.US,
                    "    {\"key\":%s,\"name\":%s,\"api\":%s,\"verdict\":\"%s\",\"detail\":%s}",
                    js(bean.getKey()), js(bean.getName()), js(bean.getApi()), verdict, js(detail)));
        }

        String ts = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date());
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"checked_at\": \"").append(ts).append("\",\n");
        sb.append("  \"total\": ").append(total).append(",\n");
        sb.append("  \"ok\": ").append(okCount.get()).append(",\n");
        sb.append("  \"fail\": ").append(total - okCount.get()).append(",\n");
        sb.append("  \"sites\": [\n");
        sb.append(join(lines)).append("\n");
        sb.append("  ]\n}\n");

        writeFile(appCtx, sb.toString());
        Hawk.put(K_LAST_RUN, System.currentTimeMillis());

        final String msg = "站点自检完成：可用 " + okCount.get() + " / " + total;
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            @Override
            public void run() {
                try {
                    Toast.makeText(appCtx, msg, Toast.LENGTH_LONG).show();
                } catch (Throwable ignored) {
                }
            }
        });
    }

    /** 返回 "OK|详细信息" 或 "NG|原因" */
    private static String checkOne(SourceBean bean) {
        long t0 = System.currentTimeMillis();
        try {
            Spider sp = ApiConfig.get().getCSP(bean);
            if (sp == null) return "NG|spider 加载失败";
            String json = sp.homeContent(false);
            long ms = System.currentTimeMillis() - t0;
            if (json == null || json.trim().isEmpty()) return "NG|返回为空";
            String t = json.trim();
            boolean usable = t.length() > 20
                    && (t.contains("\"class\"") || t.contains("\"filters\"")
                        || t.contains("\"list\"") || t.contains("\"categories\""));
            if (!usable) return "NG|返回非有效结构(" + t.length() + "B)";
            return "OK|" + ms + "ms/" + t.length() + "B";
        } catch (Throwable e) {
            String m = e.getClass().getSimpleName();
            if (e.getMessage() != null) m += ":" + e.getMessage();
            if (m.length() > 120) m = m.substring(0, 120);
            return "NG|" + m;
        }
    }

    private static void writeFile(Context ctx, String content) {
        File dir = ctx.getExternalFilesDir(null);
        if (dir == null) dir = ctx.getFilesDir();
        if (dir == null) return;
        File f = new File(dir, FILE_NAME);
        FileOutputStream fos = null;
        OutputStreamWriter w = null;
        try {
            fos = new FileOutputStream(f);
            w = new OutputStreamWriter(fos, "UTF-8");
            w.write(content);
            w.flush();
        } catch (Throwable ignored) {
        } finally {
            try { if (w != null) w.close(); } catch (Throwable ignored) { }
            try { if (fos != null) fos.close(); } catch (Throwable ignored) { }
        }
    }

    private static String join(List<String> lines) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < lines.size(); i++) {
            sb.append(lines.get(i));
            if (i < lines.size() - 1) sb.append(",\n");
        }
        return sb.toString();
    }

    private static String js(String s) {
        if (s == null) return "\"\"";
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        // 注意：这里不能用反斜杠 u 加格式串的字面量写法，
                        // Java 在词法阶段就会把反斜杠 u 当成 Unicode 转义，直接报 illegal unicode escape
                        sb.append('\\').append('u')
                          .append(String.format(Locale.US, "%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.append('"').toString();
    }
}
