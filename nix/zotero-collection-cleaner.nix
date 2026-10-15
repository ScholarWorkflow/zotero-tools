{ pkgs
, lib
, mkAgentPackage
, source
, enableHarnesses ? [ "codex" ]
}:

let
  resources = import ./skill-resources.nix {
    inherit pkgs lib source;
    python = pkgs.python311;
    skillNames = [ "zotero-collection-cleaner" ];
  };

  roleText = builtins.readFile "${source}/.apm/agents/zotero-collection-cleaner.agent.md";
  roleParts = lib.splitString "\n---\n" roleText;
  frontmatter = lib.removePrefix "---\n" (builtins.head roleParts);
  roleBody = builtins.elemAt roleParts 1;
  descriptionLine = builtins.head (builtins.filter
    (line: lib.hasPrefix "description: " line)
    (lib.splitString "\n" frontmatter));
  quotedDescription = lib.removePrefix "description: " descriptionLine;
  description = builtins.substring 1 (builtins.stringLength quotedDescription - 2) quotedDescription;

  runtimeTools = [
    pkgs.bash
    pkgs.coreutils
    pkgs.curl
    pkgs.gawk
    pkgs.gnugrep
  ];

  package = mkAgentPackage {
    inherit pkgs enableHarnesses;
    id = "zotero-collection-cleaner";
    version = "0.1.0";
    files = {
      "skills/zotero-collection-cleaner" = "${resources}/skills/zotero-collection-cleaner";
    };
    exports = {
      skills.zotero-collection-cleaner = "skills/zotero-collection-cleaner";
      agents.zotero-collection-cleaner = {
        inherit description;
        developer_instructions = roleBody;
      };
    };
    runtimePackages = runtimeTools;
  };
in
assert builtins.length roleParts == 2;
assert builtins.substring 0 1 quotedDescription == "'";
assert builtins.substring (builtins.stringLength quotedDescription - 1) 1 quotedDescription == "'";
package
