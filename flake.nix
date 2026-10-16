{
  description = "Nix packages for Zotero workflow skills and command-line tools";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    agent-env-nix = {
      url = "github:RekiDunois/agent-env-nix/ba2d0fe4ef4d1dc1d80ec628c3ecc6607829a76e";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, agent-env-nix }:
    let
      system = "aarch64-darwin";
      pkgs = nixpkgs.legacyPackages.${system};
      packages = import ./nix {
        inherit pkgs;
        lib = nixpkgs.lib;
        mkAgentPackage = agent-env-nix.lib.mkAgentPackage;
        source = self.outPath;
      };
    in
    {
      packages.${system} = packages;
    };
}
