# PepHaul Product Price List

**Source:** [Google Sheets Price List](https://docs.google.com/spreadsheets/d/18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s/edit?gid=188098807#gid=188098807&range=A3)

**Last Updated:** December 12, 2024

## How to Update Prices

1. Update prices in the [Google Sheet Price List tab](https://docs.google.com/spreadsheets/d/18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s/edit?gid=188098807#gid=188098807&range=A3)
2. Copy the updated prices from the sheet
3. Update the `get_products()` function in `app.py` (lines 924-1149)
4. Ask the AI wizard to help sync prices: `/ops_wizard sync prices from PRODUCTS.md`

## Product Categories

### Tirzepatide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| TR5 | Tirzepatide - 5mg | $45 | $4.5 | 10 |
| TR10 | Tirzepatide - 10mg | $65 | $6.5 | 10 |
| TR15 | Tirzepatide - 15mg | $75 | $7.5 | 10 |
| TR20 | Tirzepatide - 20mg | $85 | $8.5 | 10 |
| TR30 | Tirzepatide - 30mg | $105 | $10.5 | 10 |
| TR40 | Tirzepatide - 40mg | $130 | $13.0 | 10 |
| TR50 | Tirzepatide - 50mg | $155 | $15.5 | 10 |
| TR60 | Tirzepatide - 60mg | $180 | $18.0 | 10 |
| TR100 | Tirzepatide - 100mg | $285 | $28.5 | 10 |

### Semaglutide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| SM2 | Semaglutide - 2mg | $35 | $3.5 | 10 |
| SM5 | Semaglutide - 5mg | $45 | $4.5 | 10 |
| SM10 | Semaglutide - 10mg | $65 | $6.5 | 10 |
| SM15 | Semaglutide - 15mg | $75 | $7.5 | 10 |
| SM20 | Semaglutide - 20mg | $85 | $8.5 | 10 |
| SM30 | Semaglutide - 30mg | $105 | $10.5 | 10 |

### Retatrutide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| RT5 | Retatrutide - 5mg | $70 | $7.0 | 10 |
| RT10 | Retatrutide - 10mg | $100 | $10.0 | 10 |
| RT15 | Retatrutide - 15mg | $125 | $12.5 | 10 |
| RT20 | Retatrutide - 20mg | $150 | $15.0 | 10 |
| RT30 | Retatrutide - 30mg | $190 | $19.0 | 10 |
| RT40 | Retatrutide - 40mg | $235 | $23.5 | 10 |
| RT50 | Retatrutide - 50mg | $275 | $27.5 | 10 |
| RT60 | Retatrutide - 60mg | $315 | $31.5 | 10 |

### TB-500
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| BT5 | TB-500 - 5mg | $70 | $7.0 | 10 |
| BT10 | TB-500 - 10mg | $130 | $13.0 | 10 |
| BT20 | TB-500 - 20mg | $185 | $18.5 | 10 |
| B10F | TB-500 Fragment - 10mg | $90 | $9.0 | 10 |

### BPC-157
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| BC5 | BPC-157 - 5mg | $40 | $4.0 | 10 |
| BC10 | BPC-157 - 10mg | $60 | $6.0 | 10 |
| BC20 | BPC-157 - 20mg | $100 | $10.0 | 10 |

### AOD9604
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| 2AD | AOD9604 - 2mg | $50 | $5.0 | 10 |
| 5AD | AOD9604 - 5mg | $90 | $9.0 | 10 |
| 10AD | AOD9604 - 10mg | $155 | $15.5 | 10 |

### Blends
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| BB10 | BPC 5mg + TB500 5mg - 10mg | $90 | $9.0 | 10 |
| BB20 | BPC 10mg + TB500 10mg - 20mg | $155 | $15.5 | 10 |
| BBG50 | GHK-Cu + TB500 + BPC157 - 50mg | $155 | $15.5 | 10 |
| BBG70 | GHK-Cu + TB500 + BPC157 - 70mg | $175 | $17.5 | 10 |
| KLOW | GHK-Cu + TB500 + BPC157 + KPV - 80mg | $195 | $19.5 | 10 |
| Ti17 | Tesamorelin + Ipamorelin - 17mg | $170 | $17.0 | 10 |
| CS10 | Cagrilintide + Semaglutide - 10mg | $125 | $12.5 | 10 |
| RC10 | Retatrutide + Cagrilintide - 10mg | $160 | $16.0 | 10 |
| XS20 | Selank + Semax - 20mg | $95 | $9.5 | 10 |
| NM120 | NAD+ + Mots-C + 5-Amino-1MQ - 120mg | $145 | $14.5 | 10 |

### CJC-1295
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| CP10 | CJC-1295 (no DAC) + Ipamorelin - 10mg | $95 | $9.5 | 10 |
| CND5 | CJC-1295 no DAC - 5mg | $75 | $7.5 | 10 |
| CND10 | CJC-1295 no DAC - 10mg | $120 | $12.0 | 10 |
| CD2 | CJC-1295 With DAC - 2mg | $75 | $7.5 | 10 |
| CD5 | CJC-1295 With DAC - 5mg | $135 | $13.5 | 10 |
| CD10 | CJC-1295 With DAC - 10mg | $245 | $24.5 | 10 |

### Cagrilintide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| CGL5 | Cagrilintide - 5mg | $80 | $8.0 | 10 |
| CGL10 | Cagrilintide - 10mg | $130 | $13.0 | 10 |
| CGL20 | Cagrilintide - 20mg | $235 | $23.5 | 10 |

### DSIP
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| DS5 | DSIP - 5mg | $45 | $4.5 | 10 |
| DS10 | DSIP - 10mg | $65 | $6.5 | 10 |
| DS15 | DSIP - 15mg | $85 | $8.5 | 10 |

### Others
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| DR5 | Dermorphin - 5mg | $60 | $6.0 | 10 |
| ET10 | Epithalon - 10mg | $45 | $4.5 | 10 |
| ET40 | Epithalon - 40mg | $140 | $14.0 | 10 |
| ET50 | Epithalon - 50mg | $155 | $15.5 | 10 |
| E3K | EPO - 3000IU | $100 | $20.0 | 5 |
| F410 | FOXO4 - 10mg | $320 | $32.0 | 10 |
| AU100 | AHK-CU - 100mg | $70 | $7.0 | 10 |
| CU50 | GHK-CU - 50mg | $35 | $3.5 | 10 |
| CU100 | GHK-CU - 100mg | $50 | $5.0 | 10 |

### GHRP
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| G25 | GHRP-2 - 5mg | $35 | $3.5 | 10 |
| G210 | GHRP-2 - 10mg | $55 | $5.5 | 10 |
| G65 | GHRP-6 - 5mg | $35 | $3.5 | 10 |
| G610 | GHRP-6 - 10mg | $55 | $5.5 | 10 |
| GTT | Glutathione - 1500mg | $90 | $9.0 | 10 |
| GND2 | Gonadorelin - 2mg | $40 | $4.0 | 10 |

### HGH
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| H06 | HGH 191AA - 6iu | $50 | $5.0 | 10 |
| H10 | HGH 191AA - 10iu | $60 | $6.0 | 10 |
| H12 | HGH 191AA - 12iu | $70 | $7.0 | 10 |
| H15 | HGH 191AA - 15iu | $80 | $8.0 | 10 |
| H24 | HGH 191AA - 24iu | $105 | $10.5 | 10 |
| H36 | HGH 191AA - 36iu | $145 | $14.5 | 10 |
| GH100 | HGH 191AA - 100iu | $370 | $37.0 | 10 |
| HU10 | Humanin - 10mg | $185 | $18.5 | 10 |
| G75 | HMG - 75IU | $65 | $6.5 | 10 |
| HX2 | Hexarelin - 2mg | $40 | $4.0 | 10 |
| HX5 | Hexarelin - 5mg | $80 | $8.0 | 10 |
| G5K | HCG - 5000IU | $75 | $7.5 | 10 |
| G10K | HCG - 10000IU | $135 | $13.5 | 10 |
| FR2 | HGH Fragment 176-191 - 2mg | $50 | $5.0 | 10 |
| FR5 | HGH Fragment 176-191 - 5mg | $90 | $9.0 | 10 |
| HA5 | Hyaluronic Acid - 5mg | $35 | $3.5 | 10 |

### Ipamorelin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| IP5 | Ipamorelin - 5mg | $40 | $4.0 | 10 |
| IP10 | Ipamorelin - 10mg | $70 | $7.0 | 10 |

### IGF
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| IG01 | IGF-1 LR3 - 0.1mg | $40 | $4.0 | 10 |
| IG1 | IGF-1 LR3 - 1mg | $185 | $18.5 | 10 |

### KissPeptin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| KS5 | KissPeptin-10 - 5mg | $50 | $5.0 | 10 |
| KS10 | KissPeptin-10 - 10mg | $75 | $7.5 | 10 |
| KP10 | KPV - 10mg | $60 | $6.0 | 10 |
| 375 | LL37 - 5mg | $95 | $9.5 | 10 |

### MT (Melanotan)
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| MT1 | MT-1 - 10mg | $50 | $5.0 | 10 |
| ML10 | MT-2 - 10mg | $50 | $5.0 | 10 |

### MOTS-C
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| MS10 | MOTS-C - 10mg | $60 | $6.0 | 10 |
| MS40 | MOTS-C - 40mg | $175 | $17.5 | 10 |
| FM2 | MGF - 2mg | $50 | $5.0 | 10 |

### Mazdutide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| MDT5 | Mazdutide - 5mg | $115 | $11.5 | 10 |
| MDT10 | Mazdutide - 10mg | $190 | $19.0 | 10 |

### NAD+
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| NJ3100 | NAD+ - 100mg | $40 | $4.0 | 10 |
| NJ500 | NAD+ - 500mg | $75 | $7.5 | 10 |
| NJ1000 | NAD+ - 1000mg | $125 | $12.5 | 10 |

### Oxytocin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| OT2 | Oxytocin Acetate - 2mg | $40 | $4.0 | 10 |
| OT5 | Oxytocin Acetate - 5mg | $50 | $5.0 | 10 |
| OT10 | Oxytocin Acetate - 10mg | $65 | $6.5 | 10 |

### P21, PE, PEG MGF
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| P210 | P21 - 10mg | $60 | $6.0 | 10 |
| PE10 | PE 22-28 - 10mg | $50 | $5.0 | 10 |
| FMP2 | PEG MGF - 2mg | $80 | $8.0 | 10 |
| P41 | PT-141 - 10mg | $55 | $5.5 | 10 |

### Pinealon
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| PIN5 | Pinealon - 5mg | $45 | $4.5 | 10 |
| PIN10 | Pinealon - 10mg | $65 | $6.5 | 10 |
| PIN20 | Pinealon - 20mg | $95 | $9.5 | 10 |

### PNC-27
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| PN5 | PNC-27 - 5mg | $90 | $9.0 | 10 |
| PN10 | PNC-27 - 10mg | $155 | $15.5 | 10 |

### Survodutide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| SUR10 | Survodutide - 10mg | $215 | $21.5 | 10 |

### SNAP-8
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| NP810 | SNAP-8 - 10mg | $45 | $4.5 | 10 |

### SS-31
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| 2S10 | SS-31 - 10mg | $90 | $9.0 | 10 |
| 2S50 | SS-31 - 50mg | $330 | $33.0 | 10 |

### Selank
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| SK5 | Selank - 5mg | $40 | $4.0 | 10 |
| SK10 | Selank - 10mg | $60 | $6.0 | 10 |
| SK30 | Selank - 30mg | $125 | $12.5 | 10 |

### Semax
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| XA5 | Semax - 5mg | $40 | $4.0 | 10 |
| XA10 | Semax - 10mg | $60 | $6.0 | 10 |
| XA30 | Semax - 30mg | $125 | $12.5 | 10 |

### NA Selank/Semax Amidate
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| NSK30 | NA Selank Amidate - 30mg | $135 | $13.5 | 10 |
| NXA30 | NA Semax Amidate - 30mg | $135 | $13.5 | 10 |

### Sermorelin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| SMO5 | Sermorelin Acetate - 5mg | $70 | $7.0 | 10 |
| SMO10 | Sermorelin Acetate - 10mg | $115 | $11.5 | 10 |

### Tesamorelin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| TSM5 | Tesamorelin - 5mg | $80 | $8.0 | 10 |
| TSM10 | Tesamorelin - 10mg | $130 | $13.0 | 10 |
| TSM20 | Tesamorelin - 20mg | $235 | $23.5 | 10 |

### Thymosin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| TA1 | Thymosin A1 - 10mg | $90 | $9.0 | 10 |
| TB4 | Thymosin B4 - 5mg | $50 | $5.0 | 10 |

### 5-Amino-1MQ
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| 10AM | 5-Amino-1MQ - 10mg | $60 | $6.0 | 10 |
| 50AM | 5-Amino-1MQ - 50mg | $80 | $8.0 | 10 |

### Adamax
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| AD5 | Adamax - 5mg | $115 | $11.5 | 10 |

### Alprostadil
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| PRO20 | Alprostadil - 20MCG | $115 | $23.0 | 5 |

### AICAR
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| AR50 | AICAR - 50mg | $70 | $7.0 | 10 |

### ACE-031
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| AE1 | ACE-031 - 1mg | $85 | $8.5 | 10 |

### Adipotide
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| AP2 | Adipotide - 2mg | $70 | $7.0 | 10 |
| AP5 | Adipotide - 5mg | $145 | $14.5 | 10 |

### ARA-290
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| RA10 | ARA-290 - 10mg | $60 | $6.0 | 10 |

### Botulinum Toxin
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| XT100 | Botulinum Toxin - 100iu | $145 | $14.5 | 10 |

### Bioregulators
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| CA20 | Cardiogen - 20mg | $115 | $11.5 | 10 |
| COR20 | Cortagen - 20mg | $115 | $11.5 | 10 |
| CH20 | Chonluten - 20mg | $115 | $11.5 | 10 |
| LAX20 | Cartalax - 20mg | $115 | $11.5 | 10 |
| OV20 | Ovagen - 20mg | $115 | $11.5 | 10 |
| PA20 | Pancragen - 20mg | $115 | $11.5 | 10 |
| VI20 | Vilon - 20mg | $115 | $11.5 | 10 |
| TG20 | Testagen - 20mg | $115 | $11.5 | 10 |

### Water
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| AA10 | AA Water - 10ml | $15 | $1.5 | 10 |
| BA03 | BAC Water - 3ml | $15 | $1.5 | 10 |
| BA10 | BAC Water - 10ml | $15 | $1.5 | 10 |

### Lipo Blends
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| LC120 | Lipo-C 120mg (Methionine/Choline/Carnitine) | $60 | $6.0 | 10 |
| LC216 | Lipo-B 216mg (Carnitine/Arginine/B-Complex) | $65 | $6.5 | 10 |
| LC425 | Lipo-C FOCUS (ATP/Eria Jarensis/Carnitine) | $115 | $11.5 | 10 |
| LC500 | L-Carnitine 500mg | $65 | $6.5 | 10 |
| LC526 | Lipo-C FAT BLASTER (Carnitine/MIC/B12/NADH) | $115 | $11.5 | 10 |
| LC553 | SUPER SHRED (Carnitine/MIC/ATP/Albuterol) | $115 | $11.5 | 10 |
| RP226 | Relaxation PM (Gaba/Melatonin/Arginine) | $115 | $11.5 | 10 |
| SHB | SUPER Human Blend (Multi Amino Complex) | $115 | $11.5 | 10 |
| HHB | Healthy Hair Skin Nails Blend (B-Complex) | $115 | $11.5 | 10 |
| LMX | Lipo Mino Mix (B-Complex/Carnitine) | $95 | $9.5 | 10 |
| GAZ | Immunological Enhancement (Glutathione/Zinc) | $135 | $13.5 | 10 |
| SHR | SHRED (Carnitine/B12/MIC) | $105 | $10.5 | 10 |
| GGH | GHK-CU + Glutathione + Histidine + NADH | $115 | $11.5 | 10 |
| SZ352 | Sleep Blend (Gaba/Theanine/Melatonin) | $105 | $10.5 | 10 |

### Vitamins
| Code | Product | Kit Price | Vial Price | Vials/Kit |
|------|---------|-----------|------------|-----------|
| D320 | D320 (vitamins) | $75 | $7.5 | 10 |
| B1201 | B12 (small) | $40 | $4.0 | 10 |
| B1210 | B12 (large) | $75 | $7.5 | 10 |

---

**Total Products:** 150+

**Notes:**
- All prices in USD
- Default vials per kit: 10 (except where noted)
- Prices subject to change - always check Google Sheet for latest
