/*
 * Arch 软件包下游运行时组装器。
 *
 * 从 scripts/release/pack.ts 打包出的工作区 tarball 构建 @deepseek-ai/dsh 的
 * 依赖闭包（dependencies、optionalDependencies、peerDependencies）。
 * 产物只服务 Arch Linux x86_64（linux / x64 / glibc）。
 * 工作区包自己的 os、cpu、libc 与这个目标不符时，不进入安装闭包，
 * 并从其依赖方的依赖表里删掉。这样 npm 不会再把 darwin、arm64、musl
 * 之类的包当成必装依赖，也不会以 EBADPLATFORM 中断预编译。
 */

import { execFileSync } from 'node:child_process'
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { relative, resolve } from 'node:path'

const TARGET = { os: 'linux', cpu: 'x64', libc: 'glibc' }
const DEPENDENCY_SECTIONS = ['dependencies', 'optionalDependencies', 'peerDependencies']

const [srcdir] = process.argv.slice(2)
if (!srcdir) throw new Error('usage: node aur-package.mjs <srcdir>')
assertTargetHost()

const src = resolve(srcdir)
const repo = resolve(src, 'deepseek-harness')
const packages = new Map()
for (const dir of ['dist/aur-vendor', 'dist/aur-dsh']) {
  for (const file of readdirSync(resolve(repo, dir)).filter(file => file.endsWith('.tgz'))) {
    const full = resolve(repo, dir, file)
    const manifest = manifestOf(full)
    if (typeof manifest.name !== 'string' || manifest.name === '') {
      throw new Error(`${full} is missing package name`)
    }
    packages.set(manifest.name, { file: full, manifest })
  }
}

const incompatible = new Map()
for (const [name, entry] of packages) {
  const mismatches = platformMismatch(entry.manifest)
  if (mismatches.length > 0) incompatible.set(name, mismatches)
}

const install = new Set()
const skipped = new Set()
function visit(name) {
  if (install.has(name) || skipped.has(name)) return
  const entry = packages.get(name)
  if (entry === undefined) return
  const mismatches = incompatible.get(name)
  if (mismatches !== undefined) {
    skipped.add(name)
    console.error(`skip ${name}: ${mismatches.join(' ')}`)
    return
  }
  install.add(name)
  for (const section of DEPENDENCY_SECTIONS) {
    for (const dependency of Object.keys(dependencyMap(entry.manifest, section))) visit(dependency)
  }
}
visit('@deepseek-ai/dsh')
if (!install.has('@deepseek-ai/dsh')) {
  throw new Error('@deepseek-ai/dsh is missing or not installable on linux/x64/glibc')
}

for (const name of install) {
  const entry = packages.get(name)
  if (stripIncompatible(entry.manifest, incompatible)) rewriteTarball(entry.file, entry.manifest)
}

const installedNames = [...install].sort()
writeFileSync(
  resolve(src, 'runtime-tarballs.txt'),
  `${installedNames.map(name => packages.get(name).file).join('\n')}\n`,
)

const npmRoot = resolve(src, 'npm-root')
rmSync(npmRoot, { recursive: true, force: true })
mkdirSync(npmRoot, { recursive: true })
const dependencies = {}
for (const name of installedNames) {
  dependencies[name] = `file:${relative(npmRoot, packages.get(name).file).replaceAll('\\', '/')}`
}
const subprocessLocal = dependencies['@deepseek-ai/dsh-subprocess-local']
if (subprocessLocal === undefined) {
  throw new Error('runtime closure is missing @deepseek-ai/dsh-subprocess-local')
}
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

function assertTargetHost() {
  if (process.platform !== TARGET.os || process.arch !== TARGET.cpu) {
    throw new Error(
      `aur-package.mjs must run on ${TARGET.os}/${TARGET.cpu}, current is ${process.platform}/${process.arch}`,
    )
  }
  const libc = readLibcFamily()
  if (libc !== TARGET.libc) {
    throw new Error(`aur-package.mjs must run on ${TARGET.libc}, detected ${libc}`)
  }
}

function readLibcFamily() {
  const lddPath = '/usr/bin/ldd'
  let content
  try {
    content = readFileSync(lddPath, 'utf8')
  } catch (err) {
    throw new Error(`cannot read ${lddPath}: ${err.message}`)
  }
  if (content.includes('GNU C Library')) return 'glibc'
  if (content.includes('musl')) return 'musl'
  throw new Error(`${lddPath} does not identify glibc or musl`)
}

function dependencyMap(manifest, section) {
  const value = manifest[section]
  if (value === undefined) return {}
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${manifest.name}: ${section} must be an object`)
  }
  return value
}

// 与 npm-install-checks 的 checkList 一致：否定项全部不命中，且至少一个肯定项命中。
function checkList(value, list) {
  if (list.length === 1 && list[0] === 'any') return true
  let negated = 0
  let match = false
  for (const entry of list) {
    if (typeof entry !== 'string' || entry === '') {
      throw new Error(`invalid platform entry: ${JSON.stringify(entry)}`)
    }
    const negate = entry.charAt(0) === '!'
    const test = negate ? entry.slice(1) : entry
    if (negate && test === '') throw new Error(`invalid platform entry: ${entry}`)
    if (negate) {
      negated++
      if (value === test) return false
    } else {
      match = match || value === test
    }
  }
  return match || negated === list.length
}

function listEntries(value, field, pkgName) {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value
  throw new Error(`${pkgName}: ${field} must be a string or an array of strings`)
}

function platformMismatch(manifest) {
  const mismatches = []
  for (const [field, current] of [['os', TARGET.os], ['cpu', TARGET.cpu], ['libc', TARGET.libc]]) {
    if (manifest[field] === undefined) continue
    if (!checkList(current, listEntries(manifest[field], field, manifest.name))) {
      mismatches.push(`${field}=${JSON.stringify(manifest[field])}`)
    }
  }
  return mismatches
}

function stripIncompatible(manifest, incompatibleNames) {
  let changed = false
  let removedPeer = false
  for (const section of DEPENDENCY_SECTIONS) {
    const deps = manifest[section]
    if (deps === undefined) continue
    for (const name of Object.keys(dependencyMap(manifest, section))) {
      if (!incompatibleNames.has(name)) continue
      delete deps[name]
      changed = true
      removedPeer = removedPeer || section === 'peerDependencies'
      console.error(`strip ${manifest.name} ${section} ${name}`)
    }
    if (Object.keys(deps).length === 0) delete manifest[section]
  }
  if (!removedPeer) return changed
  const meta = manifest.peerDependenciesMeta
  if (meta === undefined) return changed
  if (meta === null || typeof meta !== 'object' || Array.isArray(meta)) {
    throw new Error(`${manifest.name}: peerDependenciesMeta must be an object`)
  }
  for (const name of Object.keys(meta)) {
    if (!incompatibleNames.has(name)) continue
    delete meta[name]
    changed = true
  }
  if (Object.keys(meta).length === 0) delete manifest.peerDependenciesMeta
  return changed
}

function manifestOf(tarball) {
  return JSON.parse(execFileSync('bsdtar', ['-xOf', tarball, 'package/package.json'], { encoding: 'utf8' }))
}

function rewriteTarball(tarball, manifest) {
  const dir = mkdtempSync(resolve(tmpdir(), 'aur-tarball-'))
  const repacked = `${tarball}.repack.tgz`
  try {
    execFileSync('bsdtar', ['-xf', tarball, '-C', dir])
    writeFileSync(resolve(dir, 'package/package.json'), `${JSON.stringify(manifest, null, 2)}\n`)
    execFileSync('bsdtar', ['-acf', repacked, '-C', dir, 'package'])
    renameSync(repacked, tarball)
  } finally {
    rmSync(dir, { recursive: true, force: true })
    rmSync(repacked, { force: true })
  }
}
