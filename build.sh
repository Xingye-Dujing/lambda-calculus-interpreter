ghc -O2 -split-sections -optlc-O3 -optlc-march=native -optl-Wl,--gc-sections -optl-s -threaded -rtsopts -o main main.hs

ghc -O2 -split-sections -optlc-O3 -optlc-march=native -optl-Wl,--gc-sections -optl-s -threaded -rtsopts -o extension extension.hs