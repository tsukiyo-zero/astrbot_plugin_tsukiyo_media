# 开发流程

`main` 只放**验证通过、可以随时运行**的代码。所有改动先在特性分支上做，验证没问题再合并回 `main`。

## 1. 开分支

```bash
git switch -c fix/ui-workflow-select     # 修 bug
git switch -c feat/hires-refine          # 新功能
git switch -c docs/dev-flow              # 文档
```

分支名用小写短横线，带上这次改什么。**不要直接在 `main` 上提交**。

## 2. 开发与自测

```bash
python -m unittest discover -s tests -p "test_*.py"
node --check views/studio/app.js
```

单测里 4 项依赖 `httpx`，本机没有会 skip；以容器内跑的结果为准：

```bash
docker exec xiaofeiyu-astrbot-1 sh -c \
  'cd /tmp/t/astrbot_plugin_tsukiyo_media && python -m unittest discover -s tests'
```

## 3. 真机验证

同步到容器并重启，确认启动日志和命令注册正常，再实际跑一次（页面点生成，或 QQ 里发 `/画图`）：

```bash
docker restart xiaofeiyu-astrbot-1
docker logs --since 2m xiaofeiyu-astrbot-1 | grep -E "tsukiyo_media \(|命令已注册"
```

**没跑通就不合 `main`。**

## 4. 版本号

三处保持一致：`metadata.yaml`、`__init__.py`、`main.py` 的 `@register`。

项目仍在内测，统一记 `0.0.0`，CHANGELOG 里写「开发中」；正式发版时再起版本号。

## 5. 记录

在 `CHANGELOG.md` 顶部补一条，写清楚改了什么、为什么。

## 6. 合并回 main

```bash
git switch main
git merge --no-ff fix/ui-workflow-select -m "merge: 修设置页把三档工作流写坏"
git push origin main
```

用 `--no-ff` 保留一条合并记录，以后要整体回滚某个特性，直接 revert 那一个 merge 就行。

## 7. 清理

```bash
git branch -d fix/ui-workflow-select
git push origin --delete fix/ui-workflow-select    # 远端清理（可选）
```
