package com.github.tvbox.osc.util;

import android.app.Activity;

import com.github.catvod.crawler.Spider;
import com.github.tvbox.osc.api.ApiConfig;
import com.github.tvbox.osc.bean.AbsJson;
import com.github.tvbox.osc.bean.AbsXml;
import com.github.tvbox.osc.bean.Movie;
import com.github.tvbox.osc.bean.SourceBean;
import com.github.tvbox.osc.ui.fragment.UserFragment;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

import java.util.List;

/**
 * [观影听涛] 首页「双列表」：
 *   热播横条 → 固定走豆瓣（有评分、口碑稳定）
 *   分类网格 → 走首页数据源（采集站，按更新时间倒序 = 最新）
 *
 * 只替换横条数据，不动分类/翻页逻辑；豆瓣失败时保留原列表，不会白屏。
 */
public class HomeHotDouban {

    private static volatile long lastLoad = 0L;
    private static final long MIN_INTERVAL = 10_000L;

    /** 打开表示「热播条由本类填充」，HomeActivity.updateHomeRec 看到它就跳过覆盖 */
    public static boolean enabled() {
        return true;
    }

    public static void load(final Activity act) {
        if (act == null) return;
        long now = System.currentTimeMillis();
        if (now - lastLoad < MIN_INTERVAL) return;
        lastLoad = now;

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    final SourceBean bean = findDouban();
                    if (bean == null) return;
                    Spider sp = ApiConfig.get().getCSP(bean);
                    String json = sp.homeContent(false);
                    if (json == null || json.length() < 10) return;
                    AbsJson absJson = new Gson().fromJson(json, new TypeToken<AbsJson>() {
                    }.getType());
                    if (absJson == null || absJson.list == null) return;
                    AbsXml data = absJson.toAbsXml();
                    if (data == null || data.movie == null) return;
                    final List<Movie.Video> list = data.movie.videoList;
                    if (list == null || list.isEmpty()) return;
                    for (Movie.Video v : list) {
                        if (v != null) v.sourceKey = bean.getKey();
                    }
                    act.runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (UserFragment.homeHotVodAdapter != null) {
                                UserFragment.homeHotVodAdapter.setNewData(list);
                            }
                        }
                    });
                } catch (Throwable ignored) {
                    // 豆瓣不可用时保持原列表
                }
            }
        }, "ty-douban-hot").start();
    }

    private static SourceBean findDouban() {
        List<SourceBean> all = ApiConfig.get().getSourceBeanList();
        if (all == null) return null;
        for (SourceBean b : all) {
            if (b == null) continue;
            if (b.getType() != 3) continue;
            String api = b.getApi() == null ? "" : b.getApi();
            String name = b.getName() == null ? "" : b.getName();
            String key = b.getKey() == null ? "" : b.getKey();
            if (api.contains("DouDou") || api.toLowerCase().contains("douban")
                    || name.contains("豆瓣") || "豆豆".equals(key)) {
                return b;
            }
        }
        return null;
    }
}
