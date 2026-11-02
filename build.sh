ghc -O2 -split-sections -optlc-O3 -optlc-march=native -optl-Wl,--gc-sections -optl-s -threaded -rtsopts -package containers -package haskeline -package directory -o main main.hs

ghc -O2 -split-sections -optlc-O3 -optlc-march=native -optl-Wl,--gc-sections -optl-s -threaded -rtsopts -package containers -package haskeline -package directory -o extension extension.hs
