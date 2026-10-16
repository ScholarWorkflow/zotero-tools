{ pkgs
, lib
, mkAgentPackage
, source
, enableHarnesses ? [ "codex" ]
}:

let
  python = pkgs.python312.withPackages (pythonPackages: [ pythonPackages.pymupdf ]);
  sitePackages = "lib/python3.12/site-packages";

  resources = import ./skill-resources.nix {
    inherit pkgs lib source python;
    skillNames = [ "zotero-read" "zotero-collections" "zotero-paper-tagger" ];
  };

  pythonApp = pkgs.stdenvNoCC.mkDerivation {
    pname = "zotero-tools-python";
    version = "0.1.0";
    dontUnpack = true;
    dontConfigure = true;
    dontBuild = true;
    dontCheck = true;

    installPhase = ''
      install -d "$out/${sitePackages}"
      cp -R "${source}/zotero_tools" "$out/${sitePackages}/"
    '';
  };

  runtimeTools = [
    python
    pkgs.bash
    pkgs.coreutils
    pkgs.curl
    pkgs.gawk
    pkgs.gnugrep
    pkgs.poppler-utils
  ];

  makeCli = name: module: pkgs.writeShellScriptBin name ''
    export PYTHONPATH="${pythonApp}/${sitePackages}''${PYTHONPATH:+:$PYTHONPATH}"
    export ZOTERO_TOOLS_RESOURCE_ROOT="${resources}/skills"
    export PATH="${lib.makeBinPath runtimeTools}''${PATH:+:$PATH}"
    exec "${python}/bin/python3.12" -m ${module} "$@"
  '';

  cliTagger = makeCli "zotero-paper-tagger" "zotero_tools.tagger";
  cliSession = makeCli "zotero-mcp-session" "zotero_tools.session";
  cliExporter = makeCli "zotero-item-export" "zotero_tools.item_export";

  package = mkAgentPackage {
    inherit pkgs enableHarnesses;
    id = "zotero-tools";
    version = "0.1.0";
    files = {
      "skills/zotero-read" = "${resources}/skills/zotero-read";
      "skills/zotero-collections" = "${resources}/skills/zotero-collections";
      "skills/zotero-paper-tagger" = "${resources}/skills/zotero-paper-tagger";
    };
    exports.skills = {
      zotero-read = "skills/zotero-read";
      zotero-collections = "skills/zotero-collections";
      zotero-paper-tagger = "skills/zotero-paper-tagger";
    };
    runtimePackages = runtimeTools;
  };
in
package.overrideAttrs (old: {
  buildCommand = (old.buildCommand or "") + ''
    mkdir -p "$out/bin"
    ln -s "${cliTagger}/bin/zotero-paper-tagger" "$out/bin/zotero-paper-tagger"
    ln -s "${cliSession}/bin/zotero-mcp-session" "$out/bin/zotero-mcp-session"
    ln -s "${cliExporter}/bin/zotero-item-export" "$out/bin/zotero-item-export"
  '';
})
