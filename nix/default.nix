{ pkgs, lib, mkAgentPackage, source }:

{
  zotero-tools = pkgs.callPackage ./zotero-tools.nix {
    inherit mkAgentPackage source;
  };

  zotero-collection-cleaner = pkgs.callPackage ./zotero-collection-cleaner.nix {
    inherit mkAgentPackage source;
  };
}
