#!/usr/bin/env node

import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const ui = join(root, 'ui')
const outputPath = join(root, 'THIRD_PARTY_LICENSES.txt')
const check = process.argv.includes('--check')

// @vue/devtools-api@6.6.4 declares MIT in package.json but its npm tarball
// omits the repository-level LICENSE file. Keep the text from the matching
// upstream tag here so generation remains offline and reproducible.
const licenseTextOverrides = new Map([
  [
    '@vue/devtools-api@6.6.4',
    `The MIT License (MIT)

Copyright (c) 2014-present Evan You

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.`,
  ],
])

const report = JSON.parse(
  execFileSync('pnpm', ['licenses', 'list', '--prod', '--json'], {
    cwd: ui,
    encoding: 'utf8',
  }),
)

const packages = []
for (const entries of Object.values(report)) {
  for (const entry of entries) {
    for (const packagePath of entry.paths) {
      const metadata = JSON.parse(readFileSync(join(packagePath, 'package.json'), 'utf8'))
      const candidates = [
        'LICENSE',
        'LICENSE.md',
        'LICENSE.txt',
        'LICENSE-MIT.txt',
        'COPYING',
        'license',
        'license.md',
      ]
      const licenseName = candidates.find((name) => {
        try {
          readFileSync(join(packagePath, name))
          return true
        } catch {
          return false
        }
      })
      const packageKey = `${metadata.name}@${metadata.version}`
      const licenseText = licenseName
        ? readFileSync(join(packagePath, licenseName), 'utf8').trim()
        : licenseTextOverrides.get(packageKey)
      if (!licenseText) throw new Error(`No license text found for ${packageKey}`)
      packages.push({
        name: metadata.name,
        version: metadata.version,
        license: metadata.license || entry.license,
        homepage: metadata.homepage || entry.homepage || '',
        text: licenseText,
      })
    }
  }
}

const unique = [...new Map(packages.map((pkg) => [`${pkg.name}@${pkg.version}`, pkg])).values()]
  .sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version))

const sections = unique.map((pkg) => {
  const heading = `${pkg.name}@${pkg.version} — ${pkg.license}`
  return [heading, '='.repeat(heading.length), pkg.homepage, '', pkg.text].filter(Boolean).join('\n')
})
const output = [
  'Third-party licenses for the auditview browser bundle',
  'Generated from ui/pnpm-lock.yaml; do not edit by hand.',
  '',
  ...sections.map((section) => `${section}\n`),
].join('\n')

if (check) {
  const current = readFileSync(outputPath, 'utf8')
  if (current !== output) {
    throw new Error(`${basename(outputPath)} is stale; run pnpm --dir ui licenses:generate`)
  }
} else {
  writeFileSync(outputPath, output)
}
