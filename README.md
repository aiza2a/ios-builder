# iOS Builder

一个用于构建 iOS 应用的通用 GitHub Actions 构建器。

本仓库只保存构建工作流与使用说明，不保存应用源码。工作流从私有源仓库读取代码，在 GitHub macOS Runner 上生成 Xcode 工程、编译未签名 IPA，并将最终产物发布到源仓库的私有 Release。

> Public builder · Private source · Private release

## 构建流程

```text
手动触发 Workflow
        ↓
读取私有源仓库
        ↓
安装 XcodeGen，生成 Xcode 工程
        ↓
xcodebuild archive
        ↓
打包 IPA
        ↓
发布到私有源仓库 Release
```

工作流仅支持 `workflow_dispatch`，不会因公开仓库的 Pull Request 自动执行，也不会把私有源码或 IPA 上传到本仓库。

## 配置 Secrets

在本仓库的 **Settings → Secrets and variables → Actions** 中配置：

| Secret | 用途 | 最低权限 |
|---|---|---|
| `PRIVATE_REPO_READ_TOKEN` | 读取私有源仓库 | 源仓库 `Contents: Read-only` |
| `PRIVATE_REPO_WRITE_TOKEN` | 创建私有 Release、上传 IPA | 源仓库 `Contents: Read and write` |
| `SOURCE_REPOSITORY` | 私有源仓库的 `owner/repository` | 配置值，不写入公开文件 |
| `SOURCE_PROJECT` | Xcode 工程文件名，例如 `App.xcodeproj` | 配置值 |
| `SOURCE_SCHEME` | Xcode Scheme 名称，同时用于产物前缀 | 配置值 |

建议使用 GitHub Fine-grained Personal Access Token，并只授权目标私有仓库。不要使用高权限 Classic PAT，也不要把 Token 写入 YAML、源码、README 或提交记录。

## 如何构建

1. 打开本仓库的 **Actions → Build**。
2. 点击 **Run workflow**。
3. 在 `source_ref` 中填写源仓库的分支、Tag 或 commit SHA；留空时使用 `main`。
4. 等待 `Archive`、`Package IPA` 和 `Publish private artifact` 全部成功。

## 产物命名与位置

版本号从源仓库 `project.yml` 的 `MARKETING_VERSION` 自动读取，构建编号使用 GitHub Actions 的 `run_number`。

```text
Release tag: v<MARKETING_VERSION>-<run_number>
IPA:         <SOURCE_SCHEME>-v<MARKETING_VERSION>-<run_number>.ipa
```

例如：

```text
v1.2.3-42
App-v1.2.3-42.ipa
```

构建完成后，进入私有源仓库的 **Releases** 查看和下载 IPA。公开构建仓库不会生成公开 Artifact。

当前工作流使用关闭代码签名的 Archive 参数，因此产物是**未签名 IPA**：

```text
CODE_SIGNING_ALLOWED=NO
CODE_SIGNING_REQUIRED=NO
```

如需分发到设备，需要按目标签名方案重新签名，或另行接入受保护的签名配置。

## Release 中文说明

如果源仓库根目录存在：

```text
RELEASE_NOTES_ZH.md
```

构建时会优先将其作为本次 Release 的中文说明。适合记录具体功能、修复项和已知问题，例如：

```markdown
## 本次修改

- 优化播放器底部进度条交互

## 修复问题

- 修复剪刀按钮命中区域遮挡进度条拖动
- 修复模态作品详情页 MiniPlayer 不显示

## 已验证

- macOS Archive 编译
- IPA 打包
- 私有 Release 上传
```

未提供该文件时，工作流会根据源仓库最近的 Git 提交和变更文件自动生成基础说明。

## 安全约束

- 源码仓库保持 Private；本仓库不复制源代码。
- 构建产物只上传到私有源仓库 Release。
- `PRIVATE_REPO_READ_TOKEN` 与 `PRIVATE_REPO_WRITE_TOKEN` 分离，遵循最小权限。
- 本仓库的 `main` 应启用分支保护，工作流改动需要人工审核；否则公开仓库的写入者可能修改 Workflow 并滥用私有仓库 Token。
- 不要在公开日志中输出 Secret、源码路径、完整 Token 或私有仓库标识。
- Token 应设置有效期，并在不再使用时立即撤销或轮换。

## 构建环境与限制

- Runner：`macos-15`
- 工程生成：`XcodeGen`
- 构建命令：`xcodebuild archive`
- 当前流程验证的是工程生成、编译、打包和 Release 上传，不等同于真机安装、签名或运行时回归。
- 源仓库需要提供有效的 `project.yml`、Xcode 工程配置和对应 Scheme。
