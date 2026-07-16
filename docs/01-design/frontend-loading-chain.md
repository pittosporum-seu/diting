# 谛听前端加载链分析

## 文件加载顺序

```
index.html
├── echarts CDN (regular script, sync)
├── cache.js     (module, top-level)
├── api.js       (module, imports ./cache.js)
├── charts.js    (module, uses global echarts)
├── ui.js        (module)
├── pages/dashboard.js  (module, imports ../api.js ../ui.js ../app.js)
├── pages/stock.js      (module, imports ../api.js ../charts.js ../ui.js ../app.js)
├── pages/opportunities.js
├── pages/watchlist.js
├── pages/settings.js
├── router.js    (module, imports all pages/* + ../app.js)
└── app.js       (module, imports ./api ./cache ./charts ./ui ./router)
                  → 注册 DOMContentLoaded → renderPage()
```

## 问题

1. **DOMContentLoaded 竞态**: HTML 小→瞬间解析完→DOMContentLoaded 早于外部 module 加载触发
   → app.js 注册监听时事件已过 → renderPage() 从未执行
   → 已修: `document.readyState` 检查

2. **模块 import 绕过 cache buster**: `?v=0.7.2` 只对 HTML 中的顶层 `<script>` 生效
   → 但 `stock.js` 中 `import from '../app.js'` 走浏览器模块解析，不带版本号
   → 浏览器拿到旧的 304 缓存 → 旧 app.js 无 readyState 修复 → 还是白屏

## 标准解决方案

**方案 A: importmap** (推荐，轻量)
```html
<script type="importmap">
{ "imports": {
    "./js/cache.js": "./js/cache.js?v=0.7.2",
    "./js/api.js":   "./js/api.js?v=0.7.2",
    ...
}}
</script>
```
→ 所有 import 自动走版本化 URL，无需改代码
→ 缺点: importmap 用绝对路径，需要列出所有文件

**方案 B: Caddy Cache-Control 头** (服务器端)
→ 对 .js 文件设置 `Cache-Control: no-cache`，每次强制 revalidate
→ 不改前端代码

**方案 C: 内容哈希文件名** (需要构建步骤)
→ `app.a1b2c3.js` → 每次构建生成新哈希
→ 适合有 bundler 的项目

## 推荐

**B + A 组合**: Caddy 不改（留精缓存），用 importmap 精确控制版本。
所有 import 都走版本化 URL → 每次升级改 importmap 里的版本号即可。
