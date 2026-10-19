#!/usr/bin/env bash
set -euo pipefail

install_prefix=${1:-"$HOME/.local"}
source_revision=82515aad16ceedc1061ae3777acb99c90d3d3e08
build_directory=$(mktemp -d)
trap 'rm -rf -- "$build_directory"' EXIT

git -C "$build_directory" init -q
git -C "$build_directory" remote add origin https://github.com/grobian/antiword.git
git -C "$build_directory" fetch -q --depth 1 origin "$source_revision"
git -C "$build_directory" checkout -q --detach FETCH_HEAD

# 仅构建解析组件，不运行测试或解析任何文档。
make -s -C "$build_directory" -j2 antiword \
  "PREFIX=$install_prefix" "CC=${CC:-cc}" "LD=${CC:-cc}"
install -d -m 755 "$install_prefix/bin" "$install_prefix/share/antiword"
install -m 755 "$build_directory/antiword" "$install_prefix/bin/antiword"
install -m 644 "$build_directory"/Resources/*.txt "$install_prefix/share/antiword/"
install -m 644 "$build_directory/Resources/fontnames" "$install_prefix/share/antiword/"
printf 'Installed: %s/bin/antiword\n' "$install_prefix"
