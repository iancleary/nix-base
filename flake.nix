{
  description = "A small, reproducible CLI foundation for macOS and Linux";

  inputs.nixpkgs.url = "https://flakehub.com/f/NixOS/nixpkgs/0.2605";

  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-darwin" "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      names = import ./package-names.nix;
      forbidden = [
        "ast-grep" "basecamp" "bun" "cargo" "codex" "gh" "go" "herdr"
        "just" "neovim" "nodejs" "npm" "pnpm" "python3" "rustc" "rustup"
        "stripe-cli" "typst" "uv" "yt-dlp"
      ];
      bundleFor = system:
        if builtins.elem system systems then self.packages.${system}.default
        else throw "nix-base: unsupported platform ${system}";
    in
    {
      packages = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.buildEnv {
            name = "nix-base";
            paths = map (name: pkgs.${name}) names;
            pathsToLink = [
              "/bin" "/share/man" "/share/zsh/site-functions"
              "/share/bash-completion" "/share/fish/vendor_completions.d"
            ];
          };
        });

      homeManagerModules.default = { pkgs, ... }: {
        home.packages = [ (bundleFor pkgs.stdenv.hostPlatform.system) ];
      };

      nixosModules.default = { pkgs, ... }: {
        environment.systemPackages = [ (bundleFor pkgs.stdenv.hostPlatform.system) ];
      };

      checks = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          bundle = bundleFor system;
          checkAdapter = module: option:
            let
              # The consumer supplies only its architecture. Its package set
              # cannot change the bundle selected by this flake's own lock.
              result = nixpkgs.lib.evalModules {
                specialArgs.pkgs.stdenv.hostPlatform.system = system;
                modules = [
                  module
                  { options = nixpkgs.lib.setAttrByPath (nixpkgs.lib.splitString "." option) (nixpkgs.lib.mkOption {
                      type = nixpkgs.lib.types.listOf nixpkgs.lib.types.package;
                    });
                  }
                ];
              };
            in builtins.map (package: package.outPath)
              (nixpkgs.lib.getAttrFromPath (nixpkgs.lib.splitString "." option) result.config)
              == [ bundle.outPath ];
        in {
          package-policy =
            assert names == nixpkgs.lib.unique names;
            assert nixpkgs.lib.intersectLists forbidden names == [ ];
            pkgs.runCommand "nix-base-package-policy" { } ''touch "$out"'';

          module-contract =
            assert checkAdapter self.homeManagerModules.default "home.packages";
            assert checkAdapter self.nixosModules.default "environment.systemPackages";
            pkgs.runCommand "nix-base-module-contract" { } ''touch "$out"'';

          smoke = pkgs.runCommand "nix-base-smoke" { } ''
            ${pkgs.bash}/bin/bash ${./tests/smoke.sh} ${bundle}
            touch "$out"
          '';
        });
    };
}
