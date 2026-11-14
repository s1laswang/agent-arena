# Provenance

Run with Harbor 0.25.0 on Docker Desktop / Windows 11, Sat 14 Nov ~21:10, ORACLE_POLICY=cheat, judge seeds 900000-900002 x medium, hard, separate verifier, HMAC-signed ledger. Built from branch vaishnav/canary-cheat after db62ab3 (the round-3 fixes commit that adds these files). SHA-256 of the code that ran (the files in the built task, LF line endings, as git stores them):

```
c69c6f4bf46181ede8af9041daad5f0bb99a98a0ae0101d9d30ce0c1cde6f99e  harbor/template/tests/test.sh
ea39e0d933b3ae6cbbc316fdf5b32059f7f88b546acca0b8a0b0cf21d71e8fb2  canary/redteam/harbor_cheat.py
8c187dad332006b4e173833fcead59741c0034fcf51307ccd44a301376a0e898  harbor/template/solution/cheat.py
8387bfd165ad9e77726fa69ca07cc85db74759846337d70c6aae9167aa7e1225  harbor/template/solution/solve.sh
```

`ledger_key` is this RETIRED build's signing key (published after the run). It lets anyone check that the ledgers were not edited without re-signing; because it is public, it cannot prove they are genuine.
