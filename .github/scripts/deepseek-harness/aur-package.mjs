/*
 * Arch 软件包下游运行时组装器。
 *
 * 从 scripts/release/pack.ts 打包出的工作区 tarball 构建 @deepseek-ai/dsh 的
 * 完整依赖闭包（含 dependencies、optionalDependencies 与 peerDependencies），
 * 并将平台相关的原生可选依赖交给 npm 按当前 Linux x64 环境解析。
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'

const [srcdir] = process.argv.slice(2)
if (!srcdir) throw new Error('usage: node aur-package.mjs <srcdir>')
const src = resolve(srcdir)
const repo = resolve(src, 'deepseek-harness')
const manifestOf = tarball => JSON.parse(
  execFileSync('bsdtar', ['-xOf', tarball, 'package/package.json'], { encoding: 'utf8' }),
)

// 收集 scripts/release/pack.ts 生成的所有工作区 tarball。
const packages = new Map()
for (const dir of ['dist/aur-vendor', 'dist/aur-dsh']) {
  for (const file of readdirSync(resolve(repo, dir)).filter(file => file.endsWith('.tgz'))) {
    const full = resolve(repo, dir, file)
    const manifest = manifestOf(full)
    packages.set(manifest.name, { file: full, manifest })
  }
}

// 遍历 @deepseek-ai/dsh 的工作区依赖闭包。
const seen = new Set()
function visit(name) {
  if (seen.has(name)) return
  const entry = packages.get(name)
  if (entry === undefined) return
  seen.add(name)
  for (const section of ['dependencies', 'optionalDependencies', 'peerDependencies']) {
    for (const dependency of Object.keys(entry.manifest[section] ?? {})) visit(dependency)
  }
}
visit('@deepseek-ai/dsh')
const tarballs = [...seen].sort().map(name => packages.get(name).file)
writeFileSync(resolve(src, 'runtime-tarballs.txt'), `${tarballs.join('\n')}\n`)

// 生成供 npm 物化扁平 node_modules 的根 package.json。
const npmRoot = resolve(src, 'npm-root')
rmSync(npmRoot, { recursive: true, force: true })
mkdirSync(npmRoot, { recursive: true })
const dependencies = {}
for (const tarball of tarballs) {
  const name = manifestOf(tarball).name
  dependencies[name] = `file:${relative(npmRoot, tarball).replaceAll('\\', '/')}`
}
const subprocessLocal = dependencies['@deepseek-ai/dsh-subprocess-local']
if (subprocessLocal === undefined) throw new Error('runtime closure is missing @deepseek-ai/dsh-subprocess-local')
writeFileSync(resolve(npmRoot, 'package.json'), `${JSON.stringify({
  name: 'deepseek-harness-aur-build',
  version: '0.0.0',
  private: true,
  dependencies,
  allowScripts: {
    // npm 在匹配 allowScripts 前会将本地文件 tarball 规范化为绝对路径。
    [resolve(npmRoot, subprocessLocal.slice('file:'.length))]: true,
    koffi: true,
    'node-pty': true,
    '@google/genai': false,
    protobufjs: false,
    'node-addon-require-builtin': false,
  },
}, null, 2)}\n`)
