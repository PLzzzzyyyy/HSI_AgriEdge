# sim/golden 生成记录（由 sim/gen_golden.py 写，勿手改）

数值路径：tt_net.cpp float32 + tt_hw_sim.cpp 整数投影，层间 int16 Q3.12（与板上相同）。主机 x86，`-ffp-contract=off`。

N=6 argmax=0 stepwise == tt_forward bitwise
N=10 argmax=1 stepwise == tt_forward bitwise

## n6_real 与 PC double 定点仿真（fixed_point_sim.py）的逐层差

| 层 | max abs x_out - ref | max abs ref |
|---|---|---|
| 0 | 2.748e-03 | 3.77 |
| 1 | 3.174e-03 | 3.80 |
| 2 | 3.221e-03 | 3.87 |
| 3 | 3.454e-03 | 3.91 |
| 4 | 3.511e-03 | 3.86 |
| 5 | 3.434e-03 | 3.88 |
| 6 | 3.624e-03 | 3.74 |
| 7 | 3.677e-03 | 3.74 |
| 8 | 3.760e-03 | 3.85 |
| 9 | 3.835e-03 | 3.84 |
| 10 | 3.883e-03 | 3.86 |
| 11 | 3.880e-03 | 3.88 |

logits vs model/data/golden/logits_fixed.bin: max abs dlogit = 1.149e-03, argmax 0 vs 0 -> PASS

## 文件 sha256

- n10_synth/L0_attn_f32.bin 400 909ce904cf0da504
- n10_synth/L0_k_i16.bin 52920 0f43a4964f3296c8
- n10_synth/L0_mlp_i16.bin 52920 5471e01ca26be7d9
- n10_synth/L0_q_i16.bin 52920 f210d4dcac15d853
- n10_synth/L0_stats_mlp_i32.bin 80 cd6567bf2e756ae6
- n10_synth/L0_stats_qkv_i32.bin 80 0b1b1fcf24d4ab5e
- n10_synth/L0_v_i16.bin 52920 97183cfc4c0dec2a
- n10_synth/L0_x_mid_i16.bin 52920 11f1b491cf256ecd
- n10_synth/L0_x_out_i16.bin 52920 d4bf2325a1f90078
- n10_synth/L10_attn_f32.bin 400 30f1e81bba8d3624
- n10_synth/L10_k_i16.bin 52920 8b470e684cd09d2e
- n10_synth/L10_mlp_i16.bin 52920 94ce750d311c665f
- n10_synth/L10_q_i16.bin 52920 91bcab3ee3beeb0c
- n10_synth/L10_stats_mlp_i32.bin 80 c86976037161a774
- n10_synth/L10_stats_qkv_i32.bin 80 9e03805433342d22
- n10_synth/L10_v_i16.bin 52920 c9b6821137add30a
- n10_synth/L10_x_mid_i16.bin 52920 a5da4be60386fe0b
- n10_synth/L10_x_out_i16.bin 52920 4fd9c15b08dee137
- n10_synth/L11_attn_f32.bin 400 4e556eff1f0a3d82
- n10_synth/L11_k_i16.bin 52920 4cc70b911d151792
- n10_synth/L11_mlp_i16.bin 52920 c30b32041d56f5d1
- n10_synth/L11_q_i16.bin 52920 ce9031c7c8bf9739
- n10_synth/L11_stats_mlp_i32.bin 80 3407c6f6d5987f2b
- n10_synth/L11_stats_qkv_i32.bin 80 7278d2b5c0554ebe
- n10_synth/L11_v_i16.bin 52920 8b12934a8035c775
- n10_synth/L11_x_mid_i16.bin 52920 765fc909857b9b06
- n10_synth/L11_x_out_i16.bin 52920 1af7cb7711ebf43e
- n10_synth/L1_attn_f32.bin 400 e45c822fc56f5261
- n10_synth/L1_k_i16.bin 52920 1d4f9bb69aa13766
- n10_synth/L1_mlp_i16.bin 52920 a0959af3fe6ef7aa
- n10_synth/L1_q_i16.bin 52920 e704789f8fc9af65
- n10_synth/L1_stats_mlp_i32.bin 80 72509bcdffe2bcef
- n10_synth/L1_stats_qkv_i32.bin 80 dccc0d5223c84e55
- n10_synth/L1_v_i16.bin 52920 943216af4bcb1e5c
- n10_synth/L1_x_mid_i16.bin 52920 4a5661597bf189fc
- n10_synth/L1_x_out_i16.bin 52920 c08a160ed0ecc686
- n10_synth/L2_attn_f32.bin 400 141d133160c72fad
- n10_synth/L2_k_i16.bin 52920 d56fdee9a6d22045
- n10_synth/L2_mlp_i16.bin 52920 4f6360186e4c302d
- n10_synth/L2_q_i16.bin 52920 e3255e1b4d075be0
- n10_synth/L2_stats_mlp_i32.bin 80 023b2d3e0e235a3f
- n10_synth/L2_stats_qkv_i32.bin 80 b0359590736df817
- n10_synth/L2_v_i16.bin 52920 ef658ce2012f7245
- n10_synth/L2_x_mid_i16.bin 52920 f1f16c54721fbfd5
- n10_synth/L2_x_out_i16.bin 52920 d5fba05b9901722a
- n10_synth/L3_attn_f32.bin 400 850f3a977dff9026
- n10_synth/L3_k_i16.bin 52920 dd233d7b596e5e0d
- n10_synth/L3_mlp_i16.bin 52920 9e69f882de99541d
- n10_synth/L3_q_i16.bin 52920 96194616fdb95f4e
- n10_synth/L3_stats_mlp_i32.bin 80 4d0418aa0c488e09
- n10_synth/L3_stats_qkv_i32.bin 80 888c177de2e5f424
- n10_synth/L3_v_i16.bin 52920 a1d6c3c4a340b9d1
- n10_synth/L3_x_mid_i16.bin 52920 975fc8be24a77989
- n10_synth/L3_x_out_i16.bin 52920 82b57c978cbff123
- n10_synth/L4_attn_f32.bin 400 88a71f87f574ccf9
- n10_synth/L4_k_i16.bin 52920 33c9301106e25ac1
- n10_synth/L4_mlp_i16.bin 52920 627b688d89174b61
- n10_synth/L4_q_i16.bin 52920 ec2fd7e455f8e3b7
- n10_synth/L4_stats_mlp_i32.bin 80 37137caae15941fb
- n10_synth/L4_stats_qkv_i32.bin 80 17037ca8ebf89a2e
- n10_synth/L4_v_i16.bin 52920 4edbfae2dfaaab0f
- n10_synth/L4_x_mid_i16.bin 52920 65317dbfa73c759a
- n10_synth/L4_x_out_i16.bin 52920 4c3695e653d8b36f
- n10_synth/L5_attn_f32.bin 400 9088a6ca2a65ed02
- n10_synth/L5_k_i16.bin 52920 86f64fcf6934d2ab
- n10_synth/L5_mlp_i16.bin 52920 287d0947ec285fa6
- n10_synth/L5_q_i16.bin 52920 72dcec085fc6a3ee
- n10_synth/L5_stats_mlp_i32.bin 80 10fc1c795c571dbd
- n10_synth/L5_stats_qkv_i32.bin 80 b147ccfedc1dc6ae
- n10_synth/L5_v_i16.bin 52920 18bd80e2c898288c
- n10_synth/L5_x_mid_i16.bin 52920 7931ed50009d03ab
- n10_synth/L5_x_out_i16.bin 52920 7b20d39ef63d97e5
- n10_synth/L6_attn_f32.bin 400 1122de92032b1556
- n10_synth/L6_k_i16.bin 52920 a169afaf9a22f135
- n10_synth/L6_mlp_i16.bin 52920 5038308677352e0a
- n10_synth/L6_q_i16.bin 52920 7e6fbe0dea0812c8
- n10_synth/L6_stats_mlp_i32.bin 80 d64fa73072aed7e3
- n10_synth/L6_stats_qkv_i32.bin 80 850f1b178241111d
- n10_synth/L6_v_i16.bin 52920 7f37c89cc3414c1a
- n10_synth/L6_x_mid_i16.bin 52920 71abd3816d348f15
- n10_synth/L6_x_out_i16.bin 52920 a3f1d2cc9a9256fb
- n10_synth/L7_attn_f32.bin 400 04af26c0148a5054
- n10_synth/L7_k_i16.bin 52920 5ef892e97c27c206
- n10_synth/L7_mlp_i16.bin 52920 11942ede561e713a
- n10_synth/L7_q_i16.bin 52920 4f140448799138ac
- n10_synth/L7_stats_mlp_i32.bin 80 6fb1840a772d08cf
- n10_synth/L7_stats_qkv_i32.bin 80 afb3f5f52e6d7bd4
- n10_synth/L7_v_i16.bin 52920 eb3564557dc34478
- n10_synth/L7_x_mid_i16.bin 52920 9c450afa5c9a6295
- n10_synth/L7_x_out_i16.bin 52920 e5906e5e6af2ed83
- n10_synth/L8_attn_f32.bin 400 a3d755f3dda49fb4
- n10_synth/L8_k_i16.bin 52920 2e0d53b32255f339
- n10_synth/L8_mlp_i16.bin 52920 3f120a0927a7f047
- n10_synth/L8_q_i16.bin 52920 bee3ca3c3505d70a
- n10_synth/L8_stats_mlp_i32.bin 80 9039a4419b72bf7b
- n10_synth/L8_stats_qkv_i32.bin 80 fa14bff2544564f3
- n10_synth/L8_v_i16.bin 52920 4743dc64df0135bc
- n10_synth/L8_x_mid_i16.bin 52920 d32c4ac1e5f897be
- n10_synth/L8_x_out_i16.bin 52920 ce981e6e119d3c24
- n10_synth/L9_attn_f32.bin 400 4730b2b9a1e2e167
- n10_synth/L9_k_i16.bin 52920 5985b47a17f56c87
- n10_synth/L9_mlp_i16.bin 52920 dc054550c076e519
- n10_synth/L9_q_i16.bin 52920 531c42644b7bf597
- n10_synth/L9_stats_mlp_i32.bin 80 b2099e4ffa883580
- n10_synth/L9_stats_qkv_i32.bin 80 be0265a3d5fdfda5
- n10_synth/L9_v_i16.bin 52920 93f1a3a8ce9cc5e5
- n10_synth/L9_x_mid_i16.bin 52920 0c16a00255535f4f
- n10_synth/L9_x_out_i16.bin 52920 0879b27525aaa03f
- n10_synth/logits_f32.bin 36 2fc57e904b381d45
- n10_synth/meta.txt 87 4d602f3e89d17a21
- n10_synth/patch_f32.bin 95256 05c636d3fff1199e
- n10_synth/pos_embed_f32.bin 105840 dca117717007f8ab
- n10_synth/x_embed_i16.bin 52920 a8d3b4e731eb69da
- n6_real/L0_attn_f32.bin 144 95be132615b0cc61
- n6_real/L0_k_i16.bin 31752 895d4296b9ea25bc
- n6_real/L0_mlp_i16.bin 31752 97abc806ec7cec57
- n6_real/L0_q_i16.bin 31752 e236ada6ceed26ae
- n6_real/L0_stats_mlp_i32.bin 48 599196d1099ec15c
- n6_real/L0_stats_qkv_i32.bin 48 5ac7a5433320fdc5
- n6_real/L0_v_i16.bin 31752 def1fd446fe6b944
- n6_real/L0_x_mid_i16.bin 31752 a2607d89beb7336f
- n6_real/L0_x_out_i16.bin 31752 6c9beae11b3a3766
- n6_real/L10_attn_f32.bin 144 ca9e9f49bf14053e
- n6_real/L10_k_i16.bin 31752 97e4f17cff5bf045
- n6_real/L10_mlp_i16.bin 31752 593634e80547562a
- n6_real/L10_q_i16.bin 31752 6877f99bf2b8e623
- n6_real/L10_stats_mlp_i32.bin 48 05197b2279933e24
- n6_real/L10_stats_qkv_i32.bin 48 86fc32347b763d1e
- n6_real/L10_v_i16.bin 31752 ef1ae77aca8e94c9
- n6_real/L10_x_mid_i16.bin 31752 eb201f753cc02f3f
- n6_real/L10_x_out_i16.bin 31752 575b24d43009df75
- n6_real/L11_attn_f32.bin 144 8da26bfbd769bde5
- n6_real/L11_k_i16.bin 31752 5612d05e140af259
- n6_real/L11_mlp_i16.bin 31752 4dff0ae2510360d4
- n6_real/L11_q_i16.bin 31752 c90e3d5c4685738e
- n6_real/L11_stats_mlp_i32.bin 48 214093e82f89b135
- n6_real/L11_stats_qkv_i32.bin 48 1ff3b24c166aa9f4
- n6_real/L11_v_i16.bin 31752 33a0958b7d3c82be
- n6_real/L11_x_mid_i16.bin 31752 bc459a0519bb89b1
- n6_real/L11_x_out_i16.bin 31752 d54546b5f759acc0
- n6_real/L1_attn_f32.bin 144 434a57e86f5bad6f
- n6_real/L1_k_i16.bin 31752 c0ec4f65f14039f1
- n6_real/L1_mlp_i16.bin 31752 4ec5eb93b9e93229
- n6_real/L1_q_i16.bin 31752 dc83f58ea5797341
- n6_real/L1_stats_mlp_i32.bin 48 5823584d4274b2fa
- n6_real/L1_stats_qkv_i32.bin 48 17c5bac2f90f2192
- n6_real/L1_v_i16.bin 31752 96aa01d17ba437b5
- n6_real/L1_x_mid_i16.bin 31752 85d2d3b60418a298
- n6_real/L1_x_out_i16.bin 31752 6aa2c3ef78185033
- n6_real/L2_attn_f32.bin 144 bf43fce4ff18863e
- n6_real/L2_k_i16.bin 31752 c64f017e5306e162
- n6_real/L2_mlp_i16.bin 31752 d406be67a21115e8
- n6_real/L2_q_i16.bin 31752 694afd75962ae391
- n6_real/L2_stats_mlp_i32.bin 48 7e42e7210678d99e
- n6_real/L2_stats_qkv_i32.bin 48 e5376c4817e9a36c
- n6_real/L2_v_i16.bin 31752 25aad4020234510f
- n6_real/L2_x_mid_i16.bin 31752 ae866317b69aa1ac
- n6_real/L2_x_out_i16.bin 31752 52360d36d5c6ce59
- n6_real/L3_attn_f32.bin 144 f86129ac80ae941b
- n6_real/L3_k_i16.bin 31752 1df05e2dc26b5719
- n6_real/L3_mlp_i16.bin 31752 599ee736c9d7e469
- n6_real/L3_q_i16.bin 31752 48a358ed076f21fa
- n6_real/L3_stats_mlp_i32.bin 48 959dcae1cefadc9f
- n6_real/L3_stats_qkv_i32.bin 48 990a4d01db94092a
- n6_real/L3_v_i16.bin 31752 a3907c6c8de2a720
- n6_real/L3_x_mid_i16.bin 31752 8bd2992797091592
- n6_real/L3_x_out_i16.bin 31752 8959a56d64f0abad
- n6_real/L4_attn_f32.bin 144 e59220f54ee66b27
- n6_real/L4_k_i16.bin 31752 7dd3968d82cdd541
- n6_real/L4_mlp_i16.bin 31752 4dbc5e3132e8e5b8
- n6_real/L4_q_i16.bin 31752 7b436f38e4beb2d8
- n6_real/L4_stats_mlp_i32.bin 48 eceaa9562b737028
- n6_real/L4_stats_qkv_i32.bin 48 c62b4f084100fe3b
- n6_real/L4_v_i16.bin 31752 a057cddf6ac4f554
- n6_real/L4_x_mid_i16.bin 31752 cc7a3997f77d2d73
- n6_real/L4_x_out_i16.bin 31752 b0cd7c03faa1ca73
- n6_real/L5_attn_f32.bin 144 a6bcbb2f36af33d1
- n6_real/L5_k_i16.bin 31752 b64b77a136817f2d
- n6_real/L5_mlp_i16.bin 31752 c497bcfc4f1c4c80
- n6_real/L5_q_i16.bin 31752 61d697763b06ed45
- n6_real/L5_stats_mlp_i32.bin 48 eac7cd3effe1c192
- n6_real/L5_stats_qkv_i32.bin 48 e1b78e118d6bd6ef
- n6_real/L5_v_i16.bin 31752 51bad84cffb1b1ce
- n6_real/L5_x_mid_i16.bin 31752 dfe8a017d489bd7e
- n6_real/L5_x_out_i16.bin 31752 c6fa20147377d05a
- n6_real/L6_attn_f32.bin 144 825177ae577b43ca
- n6_real/L6_k_i16.bin 31752 271471b2aed7f74e
- n6_real/L6_mlp_i16.bin 31752 36d7ef03621ef57c
- n6_real/L6_q_i16.bin 31752 8910b00925fbd718
- n6_real/L6_stats_mlp_i32.bin 48 3cca43748ade1d80
- n6_real/L6_stats_qkv_i32.bin 48 8f777068ea346a9a
- n6_real/L6_v_i16.bin 31752 629934a9b9840cbf
- n6_real/L6_x_mid_i16.bin 31752 e3becd0236a80b30
- n6_real/L6_x_out_i16.bin 31752 49cef14fa2590e3f
- n6_real/L7_attn_f32.bin 144 20054b9fe92b5596
- n6_real/L7_k_i16.bin 31752 8778d8bb6942d19c
- n6_real/L7_mlp_i16.bin 31752 bd03cbc4674c735f
- n6_real/L7_q_i16.bin 31752 4970c0c20ac0d61b
- n6_real/L7_stats_mlp_i32.bin 48 c2ace72e7ea45912
- n6_real/L7_stats_qkv_i32.bin 48 89e8b976d04ff6e7
- n6_real/L7_v_i16.bin 31752 cdd8129d751f5cad
- n6_real/L7_x_mid_i16.bin 31752 1bce2fdd66ba9c0d
- n6_real/L7_x_out_i16.bin 31752 a726e8b57a2a3eec
- n6_real/L8_attn_f32.bin 144 ab73e8d2ebad0100
- n6_real/L8_k_i16.bin 31752 8676616bb80e1371
- n6_real/L8_mlp_i16.bin 31752 b8d0a03122d562b5
- n6_real/L8_q_i16.bin 31752 9e79b2d8b7759fb5
- n6_real/L8_stats_mlp_i32.bin 48 144d301efb4a45c0
- n6_real/L8_stats_qkv_i32.bin 48 a9c9e035f350dc85
- n6_real/L8_v_i16.bin 31752 567e8decb90fad54
- n6_real/L8_x_mid_i16.bin 31752 77bd93ae7992f5af
- n6_real/L8_x_out_i16.bin 31752 468fb297e92d0265
- n6_real/L9_attn_f32.bin 144 e8a0c48b246e84df
- n6_real/L9_k_i16.bin 31752 265bd4b6a0f9966f
- n6_real/L9_mlp_i16.bin 31752 d58cfd5e03b59855
- n6_real/L9_q_i16.bin 31752 6dbbd55306e26d4c
- n6_real/L9_stats_mlp_i32.bin 48 487a73317a56788e
- n6_real/L9_stats_qkv_i32.bin 48 6a0126d1764b682c
- n6_real/L9_v_i16.bin 31752 186d86a6fe36f20a
- n6_real/L9_x_mid_i16.bin 31752 ab57d24a81f9d567
- n6_real/L9_x_out_i16.bin 31752 a28fdd9c57b9f269
- n6_real/logits_f32.bin 36 2889846c2fe8754f
- n6_real/meta.txt 124 69d049b3da7b97ac
- n6_real/patch_f32.bin 52920 d2dd02cd400b5945
- n6_real/pos_embed_f32.bin 63504 d456b08bc8f012a3
- n6_real/x_embed_i16.bin 31752 270d06b33cf9c11f
