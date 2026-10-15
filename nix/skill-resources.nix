{ pkgs, lib, source, skillNames, python }:

let
  hasSkill = name: builtins.elem name skillNames;
  bash = "${pkgs.bash}/bin/bash";
  curl = "${pkgs.curl}/bin/curl";
  coreutils = "${pkgs.coreutils}/bin";
  grep = "${pkgs.gnugrep}/bin/grep";
  awk = "${pkgs.gawk}/bin/awk";
  pdftotext = "${pkgs.poppler-utils}/bin/pdftotext";
in
pkgs.runCommand "zotero-skills-${builtins.concatStringsSep "-" skillNames}" {
  nativeBuildInputs = [ pkgs.coreutils ];
} ''
  mkdir -p "$out/skills"
  ${lib.concatMapStringsSep "\n" (name: ''
    cp -R "${source}/.apm/skills/${name}" "$out/skills/"
  '') skillNames}
  chmod -R u+w "$out/skills"

  ${lib.optionalString (hasSkill "zotero-read") ''
    substituteInPlace "$out/skills/zotero-read/SKILL.md" \
      --replace-fail 'uv run' '${python}/bin/python3.12' \
      --replace-fail 'curl -' '${curl} -' \
      --replace-fail 'bash "<skill_dir>' '${bash} "<skill_dir>'
    substituteInPlace "$out/skills/zotero-read/scripts/new-session.sh" \
      --replace-fail '#!/bin/bash' '#!${bash}' \
      --replace-fail 'HDR=$(mktemp)' 'HDR=$(${coreutils}/mktemp)' \
      --replace-fail 'curl ' '${curl} ' \
      --replace-fail 'grep ' '${grep} ' \
      --replace-fail 'tr -' '${coreutils}/tr -' \
      --replace-fail 'awk ' '${awk} '
    substituteInPlace "$out/skills/zotero-read/scripts/zotero_item_export.py" \
      --replace-fail '#!/usr/bin/env python3' '#!${python}/bin/python3.12' \
      --replace-fail 'uv run ' '${python}/bin/python3.12 ' \
      --replace-fail '["bash",' '["${bash}",'
    substituteInPlace "$out/skills/zotero-read/scripts/item_export_core.py" \
      --replace-fail '"curl",' '"${curl}",'
  ''}

  ${lib.optionalString (hasSkill "zotero-collections") ''
    substituteInPlace "$out/skills/zotero-collections/SKILL.md" \
      --replace-fail 'HDR=$(mktemp)' 'HDR=$(${coreutils}/mktemp)' \
      --replace-fail 'curl -' '${curl} -' \
      --replace-fail 'grep -' '${grep} -' \
      --replace-fail 'tr -' '${coreutils}/tr -' \
      --replace-fail 'awk ' '${awk} '
  ''}

  ${lib.optionalString (hasSkill "zotero-paper-tagger") ''
    substituteInPlace "$out/skills/zotero-paper-tagger/SKILL.md" \
      --replace-fail 'python3 ' '${python}/bin/python3.12 '
    substituteInPlace "$out/skills/zotero-paper-tagger/scripts/corresp_extractor.py" \
      --replace-fail '["pdftotext",' '["${pdftotext}",'
  ''}

  ${lib.optionalString (hasSkill "zotero-collection-cleaner") ''
    substituteInPlace "$out/skills/zotero-collection-cleaner/SKILL.md" \
      --replace-fail 'HDR=$(mktemp)' 'HDR=$(${coreutils}/mktemp)' \
      --replace-fail 'curl -' '${curl} -' \
      --replace-fail 'grep -' '${grep} -' \
      --replace-fail 'tr -' '${coreutils}/tr -' \
      --replace-fail 'awk ' '${awk} '
  ''}
''
