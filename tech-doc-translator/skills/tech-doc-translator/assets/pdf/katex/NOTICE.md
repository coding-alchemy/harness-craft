# KaTeX 离线资产来源说明

本目录是从 KaTeX 0.18.7 官方发行包（npm `katex@0.18.7`，`dist/`）裁剪出的离线渲染资产：

- `katex.min.js`、`katex.min.css`：原样取自 `dist/`；CSS 中每个 `@font-face` 的 `src`
  仅保留 `woff2` 一项，`woff` 与 `truetype`（`.ttf`）两项被移除以减小体积。
  20 条 `@font-face` 规则与选择器均未改动。
- `fonts/*.woff2`：`dist/fonts/` 中全部 20 个 woff2 字体原样复制。
- `LICENSE`：KaTeX 的 MIT 许可证原件。

裁剪仅为去掉 Chromium 打印用不到的备选字体格式，未修改任何字体或脚本逻辑。
升级 KaTeX 时需重新执行同样裁剪并保留 LICENSE。
