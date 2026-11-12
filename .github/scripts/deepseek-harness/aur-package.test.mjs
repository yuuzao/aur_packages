import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(new URL('./aur-package.mjs', import.meta.url))

test('linux x64 glibc closure drops incompatible workspace packages', () => {
  const src = mkdtempSync(join(tmpdir(), 'aur-package-'))
  try {
    const dist = join(src, 'deepseek-harness/dist/aur-dsh')
    mkdirSync(join(src, 'deepseek-harness/dist/aur-vendor'), { recursive: true })
    mkdirSync(dist, { recursive: true })
    pack(dist, {
      name: '@deepseek-ai/dsh',
      dependencies: {
        '@deepseek-ai/dsh-subprocess-local': '1.0.0',
        '@deepseek-ai/dsh-darwin-tool': '1.0.0',
        '@deepseek-ai/dsh-musl-tool': '1.0.0',
      },
      optionalDependencies: {
        '@deepseek-ai/dsh-darwin-optional': '1.0.0',
      },
      peerDependencies: {
        '@deepseek-ai/dsh-linux-peer': '1.0.0',
        '@deepseek-ai/dsh-darwin-peer': '1.0.0',
      },
      peerDependenciesMeta: {
        '@deepseek-ai/dsh-darwin-peer': { optional: true },
        '@deepseek-ai/dsh-linux-peer': { optional: false },
      },
    })
    pack(dist, {
      name: '@deepseek-ai/dsh-subprocess-local',
      dependencies: { '@deepseek-ai/dsh-glibc-tool': '1.0.0' },
    })
    pack(dist, {
      name: '@deepseek-ai/dsh-darwin-tool',
      os: ['darwin'],
      dependencies: { '@deepseek-ai/dsh-only-via-darwin': '1.0.0' },
    })
    pack(dist, { name: '@deepseek-ai/dsh-only-via-darwin', version: '1.0.0' })
    pack(dist, { name: '@deepseek-ai/dsh-darwin-optional', os: ['darwin'], cpu: ['arm64'] })
    pack(dist, { name: '@deepseek-ai/dsh-musl-tool', os: 'linux', cpu: 'x64', libc: ['musl'] })
    pack(dist, { name: '@deepseek-ai/dsh-darwin-peer', os: ['!linux'] })
    pack(dist, { name: '@deepseek-ai/dsh-linux-peer', os: ['!win32'], cpu: ['any'] })
    pack(dist, { name: '@deepseek-ai/dsh-glibc-tool', os: ['linux'], cpu: ['x64'], libc: ['glibc'] })

    execFileSync(process.execPath, [script, src], { stdio: 'inherit' })

    const root = JSON.parse(readFileSync(join(src, 'npm-root/package.json'), 'utf8'))
    assert.deepEqual(Object.keys(root.dependencies).sort(), [
      '@deepseek-ai/dsh',
      '@deepseek-ai/dsh-glibc-tool',
      '@deepseek-ai/dsh-linux-peer',
      '@deepseek-ai/dsh-subprocess-local',
    ])
    assert.equal(root.optionalDependencies, undefined)

    const dsh = readTarballManifest(join(dist, 'deepseek-ai-dsh.tgz'))
    assert.deepEqual(dsh.dependencies, { '@deepseek-ai/dsh-subprocess-local': '1.0.0' })
    assert.equal(dsh.optionalDependencies, undefined)
    assert.deepEqual(dsh.peerDependencies, { '@deepseek-ai/dsh-linux-peer': '1.0.0' })
    assert.deepEqual(dsh.peerDependenciesMeta, { '@deepseek-ai/dsh-linux-peer': { optional: false } })
  } finally {
    rmSync(src, { recursive: true, force: true })
  }
})

function pack(dist, manifest) {
  const stage = mkdtempSync(join(tmpdir(), 'aur-pack-'))
  try {
    mkdirSync(join(stage, 'package'))
    writeFileSync(join(stage, 'package/package.json'), JSON.stringify(manifest))
    const filename = `${manifest.name.replace('@', '').replace('/', '-')}.tgz`
    execFileSync('bsdtar', ['-acf', join(dist, filename), '-C', stage, 'package'])
  } finally {
    rmSync(stage, { recursive: true, force: true })
  }
}

function readPackage(path) {
  return execFileSync('bsdtar', ['-xOf', path, 'package/package.json'], { encoding: 'utf8' })
}

function readTarballManifest(path) {
  return JSON.parse(readPackage(path))
}
