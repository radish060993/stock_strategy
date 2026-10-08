# Watchlist

以表格維護。`market` 填 `TW` 或 `US`；台股代號需含 `.TW`（上市）或 `.TWO`（上櫃）。
以 `#` 開頭的 symbol 會被略過。
`note` 以 `tv:` 開頭的列由 `skills/tv_screener.py` 自動維護，會被覆寫；手動加入的列請勿使用此前綴。

## TradingView 來源與篩選方式

- `tw_screener`（台股）：市值 ≥ 50 億 TWD；收盤價 ≥ 日線 SMA 200；近 1 個月成交金額（Price × volume）> 100 億 TWD；1 年 Beta > 1。
- `us_screener`（美股）：市值 ≥ 20 億 USD；收盤價 ≥ 日線 SMA 200；近 1 個月成交金額（Price × volume）> 9 億 USD；1 年 Beta > 1。
- `tw_best`（台股）：TradingView [台股 Best performing 強勢股清單](https://www.tradingview.com/markets/stocks-taiwan/market-movers-best-performing/)；依該頁面的強勢股排序與清單，不額外套用上述 screener 條件。
- `us_best`（美股）：TradingView [美股 Best performing 強勢股清單](https://www.tradingview.com/markets/stocks-usa/market-movers-best-performing/)；依該頁面的強勢股排序與清單，不額外套用上述 screener 條件。

| symbol | market | name | note |
|--------|--------|------|------|
| 2330.TW | TW | 台積電 |  |
| 2317.TW | TW | 鴻海 |  |
| AAPL | US | Apple |  |
| NVDA | US | NVIDIA |  |
| TSM | US | TSMC ADR |  |
| 2454.TW | TW | MediaTek Inc | tv:tw_screener,tw_best |
| 2308.TW | TW | Delta Electronics, Inc. | tv:tw_screener |
| 3711.TW | TW | ASE Technology Holding Co., Ltd. | tv:tw_screener,tw_best |
| 1303.TW | TW | Nan Ya Plastics Corporation | tv:tw_screener,tw_best |
| 2383.TW | TW | Elite Material Co., Ltd. | tv:tw_screener,tw_best |
| 3037.TW | TW | Unimicron Technology Corp. | tv:tw_screener,tw_best |
| 2303.TW | TW | United Microelectronics Corp. | tv:tw_screener,tw_best |
| 2408.TW | TW | Nanya Technology Corporation | tv:tw_screener,tw_best |
| 3017.TW | TW | Asia Vital Components Co., Ltd. | tv:tw_screener |
| 2382.TW | TW | Quanta Computer Inc. | tv:tw_screener |
| 2327.TW | TW | Yageo Corporation | tv:tw_screener,tw_best |
| 6669.TW | TW | Wiwynn Corporation | tv:tw_screener |
| 2059.TW | TW | King Slide Works Co., Ltd. | tv:tw_screener |
| 2345.TW | TW | Accton Technology Corp. | tv:tw_screener |
| 3443.TW | TW | Global Unichip Corp. | tv:tw_screener,tw_best |
| 7769.TW | TW | Hon. Precision, Inc. | tv:tw_screener |
| 2360.TW | TW | Chroma Ate Inc. | tv:tw_screener,tw_best |
| 8046.TW | TW | Nan Ya Printed Circuit Board Corporation | tv:tw_screener,tw_best |
| 2344.TW | TW | Winbond Electronics Corp. | tv:tw_screener,tw_best |
| 5274.TWO | TW | ASPEED Technology, Inc. | tv:tw_screener |
| 2301.TW | TW | Lite-On Technology Corp. | tv:tw_screener |
| 2368.TW | TW | Gold Circuit Electronics Ltd | tv:tw_screener |
| 4958.TW | TW | Zhen Ding Technology Holding Limited | tv:tw_screener,tw_best |
| 3231.TW | TW | Wistron Corporation | tv:tw_screener |
| 6488.TWO | TW | GlobalWafers Co., Ltd. | tv:tw_screener |
| 3189.TW | TW | Kinsus Interconnect Technology Corp. | tv:tw_screener,tw_best |
| 6274.TWO | TW | Taiwan Union Technology Corporation | tv:tw_screener,tw_best |
| 8299.TWO | TW | Phison Electronics Corp. | tv:tw_screener |
| 3481.TW | TW | Innolux Corp. | tv:tw_screener,tw_best |
| 2449.TW | TW | King Yuan Electronics Co., Ltd. | tv:tw_screener |
| 3661.TW | TW | Alchip Technologies Ltd. | tv:tw_screener |
| 5347.TWO | TW | Vanguard International Semiconductor Corp | tv:tw_screener |
| 6770.TW | TW | Powerchip Semiconductor Manufacturing Corp. | tv:tw_screener |
| 2313.TW | TW | Compeq Manufacturing Co., Ltd. | tv:tw_screener |
| 3081.TWO | TW | LandMark Optoelectronics Corp. | tv:tw_screener,tw_best |
| 6213.TW | TW | ITEQ Corporation | tv:tw_screener,tw_best |
| 2376.TW | TW | Gigabyte Technology Co., Ltd. | tv:tw_screener |
| 3105.TWO | TW | Win Semiconductors Corp. | tv:tw_screener,tw_best |
| 6239.TW | TW | Powertech Technology Inc. | tv:tw_screener |
| 3529.TWO | TW | eMemory Technology, Inc. | tv:tw_screener |
| 2492.TW | TW | Walsin Technology Corporation | tv:tw_screener,tw_best |
| 6139.TW | TW | L&K Engineering Co. Ltd. | tv:tw_screener |
| 3532.TW | TW | Formosa Sumco Technology Corporation | tv:tw_screener,tw_best |
| 1802.TW | TW | Taiwan Glass Industry Corp. | tv:tw_screener |
| 6531.TW | TW | AP Memory Technology Corp. | tv:tw_screener |
| 6147.TWO | TW | Chipbond Technology Corporation | tv:tw_screener,tw_best |
| 8996.TW | TW | Kaori Heat Treatment Co., Ltd. | tv:tw_screener,tw_best |
| 3324.TWO | TW | AURAS Technology Co., Ltd. | tv:tw_screener |
| 6257.TW | TW | Sigurd Microelectronics Corp. | tv:tw_screener |
| 5483.TWO | TW | Sino-American Silicon Products Inc. | tv:tw_screener |
| 8358.TWO | TW | CO-TECH DEVELOPMENT CORP. | tv:tw_screener |
| 3374.TWO | TW | Xintec Inc. | tv:tw_screener,tw_best |
| 3026.TW | TW | Holy Stone Enterprise Co., Ltd. | tv:tw_screener,tw_best |
| 6442.TW | TW | EZconn Corp. | tv:tw_screener |
| 6285.TW | TW | WNC Corporation | tv:tw_screener |
| 5536.TWO | TW | Acter Group Corporation Limited | tv:tw_screener |
| 3491.TWO | TW | Universal Microwave Technology, Inc. | tv:tw_screener,tw_best |
| 3264.TWO | TW | Ardentec Corporation | tv:tw_screener |
| 2455.TW | TW | Visual Photonics Epitaxy Co., Ltd. | tv:tw_screener,tw_best |
| 8150.TW | TW | ChipMOS Technologies, Inc. | tv:tw_screener,tw_best |
| 8021.TW | TW | Topoint Technology Co., Ltd. | tv:tw_screener,tw_best |
| 4979.TWO | TW | Luxnet Corporation | tv:tw_screener |
| 6182.TWO | TW | Wafer Works Corp. | tv:tw_screener,tw_best |
| 1815.TWO | TW | Fulltech Fiber Glass Corp. | tv:tw_screener |
| 3006.TW | TW | Elite Semiconductor Microelectronics Technology Inc. | tv:tw_screener |
| 3450.TW | TW | Elite Advanced Laser Corporation | tv:tw_screener |
| 3363.TWO | TW | FOCI Fiber Optic Communications, Inc. | tv:tw_screener |
| 3042.TW | TW | TXC Corporation | tv:tw_screener |
| 6278.TW | TW | Taiwan Surface Mounting Technology Corp. | tv:tw_screener |
| 4919.TW | TW | Nuvoton Technology Corporation | tv:tw_screener |
| 2481.TW | TW | Pan Jit International Inc. | tv:tw_screener |
| 3163.TWO | TW | Browave Corporation | tv:tw_screener,tw_best |
| 3211.TWO | TW | Dynapack International Technology Corporation | tv:tw_screener |
| 4991.TWO | TW | GCS Holdings, Inc. | tv:tw_screener,tw_best |
| 6173.TWO | TW | Prosperity Dielectrics Co., Ltd. | tv:tw_screener |
| 6683.TWO | TW | Keystone Microtech Co. | tv:tw_screener,tw_best |
| 2464.TW | TW | Mirle Automation Corp. | tv:tw_screener |
| 6672.TW | TW | Ventec International Group Co., Ltd. | tv:tw_screener,tw_best |
| 3707.TWO | TW | Episil Technologies Inc. | tv:tw_screener |
| 2426.TW | TW | Tyntek Corporation | tv:tw_screener,tw_best |
| 3693.TWO | TW | AIC, Inc. | tv:tw_screener |
| 3605.TW | TW | ACES Electronics Co., Ltd. | tv:tw_screener |
| 8086.TWO | TW | Advanced Wireless Semiconductor Co. | tv:tw_screener |
| 5425.TWO | TW | Taiwan Semiconductor Co., Ltd. | tv:tw_screener |
| 2340.TW | TW | Taiwan-Asia Semiconductor Corporation | tv:tw_screener |
| 3624.TWO | TW | Viking Tech Corporation | tv:tw_screener,tw_best |
| 6207.TWO | TW | Laser Tek Taiwan Co., Ltd. | tv:tw_screener |
| 2484.TW | TW | Siward Crystal Technology Co., Ltd | tv:tw_screener,tw_best |
| 7610.TW | TW | LIANYOU METALS CO.,LTD. | tv:tw_best |
| 6696.TWO | TW | Lin BioScience, Inc. | tv:tw_best |
| 4573.TWO | TW | GMT Global Inc. | tv:tw_best |
| 7856.TWO | TW | Hermes Testing Solutions Inc. | tv:tw_best |
| 3441.TWO | TW | Unique Opto-Electronics Co.,Ltd | tv:tw_best |
| 6990.TWO | TW | Plum-Monix Industry Co Ltd | tv:tw_best |
| 2221.TWO | TW | Tachia Yung Ho Machine Industry Co., Ltd. | tv:tw_best |
| 5386.TWO | TW | Albatron Technology Co., Ltd | tv:tw_best |
| 6226.TW | TW | Para Light Electronics Co., Ltd. | tv:tw_best |
| 6225.TW | TW | aiPlex Corporation | tv:tw_best |
| 7861.TWO | TW | Bellwether Electronic Corp. | tv:tw_best |
| 4556.TWO | TW | Bright Sheland International Co Ltd | tv:tw_best |
| 2305.TW | TW | Microtek International, Inc. | tv:tw_best |
| 3234.TWO | TW | Truelight Corporation | tv:tw_best |
| 5246.TWO | TW | ProbeLeader Co Ltd | tv:tw_best |
| 3167.TW | TW | Ta Liang Technology Co., Ltd. | tv:tw_best |
| 4542.TWO | TW | Asia Neo Tech Industrial Co., Ltd. | tv:tw_best |
| 6820.TWO | TW | Acon Optics Communications, Inc. | tv:tw_best |
| 7866.TWO | TW | DLI Memory, Inc. | tv:tw_best |
| 2243.TW | TW | Horng Shiue Holding Co., Ltd. | tv:tw_best |
| 4764.TW | TW | Double Bond Chemical Ind., Co., Ltd. | tv:tw_best |
| 3117.TWO | TW | Tecstar Technology Co., Ltd. | tv:tw_best |
| 8039.TW | TW | TAIFLEX Scientific Co., Ltd. | tv:tw_best |
| 6715.TW | TW | Lintes Technology Co., Ltd. | tv:tw_best |
| 4537.TWO | TW | Shuz Tung Machinery Industrial Co., Ltd. | tv:tw_best |
| 3585.TWO | TW | Advance Materials Corporation | tv:tw_best |
| 7853.TWO | TW | Cheng Mei Instrument Technology Co., Ltd. | tv:tw_best |
| 3498.TWO | TW | USUN Technology Co.,Ltd | tv:tw_best |
| 6426.TW | TW | Apogee Optocom Co., Ltd. | tv:tw_best |
| 2337.TW | TW | Macronix International Co., Ltd. | tv:tw_best |
| 6834.TW | TW | Ever Ohms Technology Co. Ltd. | tv:tw_best |
| 7875.TWO | TW | Altos Computing, Inc. | tv:tw_best |
| 4973.TWO | TW | Silicon Power Computer & Communications Inc. | tv:tw_best |
| 6538.TWO | TW | Brave C&H Supply Co., Ltd. | tv:tw_best |
| 7828.TWO | TW | Innostar Service Inc | tv:tw_best |
| 6141.TW | TW | Plotech Co. Ltd. | tv:tw_best |
| 3135.TW | TW | Goldkey Technology Corp | tv:tw_best |
| 7729.TWO | TW | Steminent Biotherapeutics, Inc. | tv:tw_best |
| 7781.TWO | TW | TPIsoftware Corp. | tv:tw_best |
| 6187.TWO | TW | All Ring Tech Co., Ltd. | tv:tw_best |
| 3595.TWO | TW | Alliance Material Co., Ltd. | tv:tw_best |
| 5464.TWO | TW | Lin Horn Technology Co., Ltd. | tv:tw_best |
| 6861.TW | TW | InnoCare Optoelectronics Corp. | tv:tw_best |
| 7669.TWO | TW | Suregiant Technology Co. Ltd. | tv:tw_best |
| 6265.TWO | TW | Kuen Chaang Uppertech Corp. | tv:tw_best |
| 7742.TWO | TW | Uranus Chemicals Co. Ltd. | tv:tw_best |
| 4925.TWO | TW | JMicron Technology Corporation | tv:tw_best |
| 4971.TWO | TW | IntelliEPI Inc. (Cayman) | tv:tw_best |
| 6849.TWO | TW | Chyi Ding Technologies Co. Ltd. | tv:tw_best |
| 6907.TWO | TW | Artery Technology Corporation | tv:tw_best |
| 3055.TW | TW | Spirox Corporation | tv:tw_best |
| 6588.TWO | TW | East Tender Optoelectronics Corp. | tv:tw_best |
| 1709.TW | TW | Formosan Union Chemical Corp. | tv:tw_best |
| 5289.TWO | TW | Innodisk Corp. | tv:tw_best |
| 7902.TWO | TW | Uwell Biopharma Inc. | tv:tw_best |
| 7717.TWO | TW | Lightel Corp | tv:tw_best |
| 3229.TW | TW | Cheer Time Enterprise Co., Ltd. | tv:tw_best |
| 6658.TW | TW | SynPower Co., Ltd. | tv:tw_best |
| 6223.TWO | TW | MPI Corporation | tv:tw_best |
| 4707.TWO | TW | Pan Asia Chemical Corp. | tv:tw_best |
| 2061.TWO | TW | Feng Ching Metal Corporation | tv:tw_best |
| 5228.TWO | TW | Max Echo Technology Corp | tv:tw_best |
| 6693.TWO | TW | Inergy Technology, Inc. | tv:tw_best |
| GOOGL | US | Alphabet Inc. | tv:us_screener |
| GOOG | US | Alphabet Inc. | tv:us_screener |
| MSFT | US | Microsoft Corporation | tv:us_screener |
| AMZN | US | Amazon.com, Inc. | tv:us_screener |
| META | US | Meta Platforms, Inc. | tv:us_screener |
| AVGO | US | Broadcom Inc. | tv:us_screener |
| MU | US | Micron Technology, Inc. | tv:us_screener,us_best |
| AMD | US | Advanced Micro Devices, Inc. | tv:us_screener,us_best |
| ASML | US | ASML Holding N.V. - New York Registry Shares | tv:us_screener |
| INTC | US | Intel Corporation | tv:us_screener,us_best |
| PLTR | US | Palantir Technologies Inc. | tv:us_screener |
| AMAT | US | Applied Materials, Inc. | tv:us_screener |
| LRCX | US | Lam Research Corporation | tv:us_screener |
| DELL | US | Dell Technologies Inc. | tv:us_screener,us_best |
| PANW | US | Palo Alto Networks, Inc. | tv:us_screener |
| ARM | US | Arm Holdings plc | tv:us_screener |
| ANET | US | Arista Networks, Inc. | tv:us_screener |
| CRWD | US | CrowdStrike Holdings, Inc. | tv:us_screener |
| TXN | US | Texas Instruments Incorporated | tv:us_screener |
| KLAC | US | KLA Corporation | tv:us_screener |
| MRVL | US | Marvell Technology, Inc. | tv:us_screener,us_best |
| SAP | US | SAP SE | tv:us_screener |
| SNDK | US | Sandisk Corporation | tv:us_screener,us_best |
| BHP | US | BHP Group Limited | tv:us_screener |
| APH | US | Amphenol Corporation | tv:us_screener |
| SHOP | US | Shopify Inc. | tv:us_screener |
| C | US | Citigroup, Inc. | tv:us_screener |
| ADI | US | Analog Devices, Inc. | tv:us_screener |
| QCOM | US | QUALCOMM Incorporated | tv:us_screener |
| STX | US | Seagate Technology Holdings PLC | tv:us_screener,us_best |
| DIS | US | Walt Disney Company (The) | tv:us_screener |
| BLK | US | BlackRock, Inc. | tv:us_screener |
| SCCO | US | Southern Copper Corporation | tv:us_screener |
| IBKR | US | Interactive Brokers Group, Inc. | tv:us_screener |
| WDC | US | Western Digital Corporation | tv:us_screener,us_best |
| NOW | US | ServiceNow, Inc. | tv:us_screener |
| GLW | US | Corning Incorporated | tv:us_screener |
| NEM | US | Newmont Corporation | tv:us_screener |
| SNOW | US | Snowflake Inc. | tv:us_screener |
| FCX | US | Freeport-McMoRan, Inc. | tv:us_screener |
| ASX | US | ASE Technology Holding Co., Ltd. | tv:us_screener |
| LITE | US | Lumentum Holdings Inc. | tv:us_screener,us_best |
| HOOD | US | Robinhood Markets, Inc. | tv:us_screener |
| CDNS | US | Cadence Design Systems, Inc. | tv:us_screener |
| SNPS | US | Synopsys, Inc. | tv:us_screener |
| ABNB | US | Airbnb, Inc. | tv:us_screener |
| MELI | US | MercadoLibre, Inc. | tv:us_screener |
| EMR | US | Emerson Electric Company | tv:us_screener |
| BE | US | Bloom Energy Corporation | tv:us_screener,us_best |
| RACE | US | Ferrari N.V. | tv:us_screener |
| DASH | US | DoorDash, Inc. | tv:us_screener |
| NU | US | Nu Holdings Ltd. | tv:us_screener |
| GM | US | General Motors Company | tv:us_screener |
| MPWR | US | Monolithic Power Systems, Inc. | tv:us_screener |
| ALAB | US | Astera Labs, Inc. | tv:us_screener |
| COHR | US | Coherent Corp. | tv:us_screener,us_best |
| KEYS | US | Keysight Technologies Inc. | tv:us_screener |
| NBIS | US | Nebius Group N.V. | tv:us_screener |
| TER | US | Teradyne, Inc. | tv:us_screener,us_best |
| CIEN | US | Ciena Corporation | tv:us_screener,us_best |
| TEL | US | TE Connectivity plc | tv:us_screener |
| FIX | US | Comfort Systems USA, Inc. | tv:us_screener |
| WPM | US | Wheaton Precious Metals Corp | tv:us_screener |
| NOK | US | Nokia Corporation Sponsored | tv:us_screener |
| MSTR | US | Strategy Inc | tv:us_screener |
| UMC | US | United Microelectronics Corporation (NEW) | tv:us_screener |
| NTRA | US | Natera, Inc. | tv:us_screener |
| DAL | US | Delta Air Lines, Inc. | tv:us_screener |
| GRMN | US | Garmin Ltd. | tv:us_screener |
| STM | US | STMicroelectronics N.V. | tv:us_screener |
| P | US | Everpure, Inc. | tv:us_screener |
| TEAM | US | Atlassian Corporation | tv:us_screener |
| ROK | US | Rockwell Automation, Inc. | tv:us_screener |
| HUM | US | Humana Inc. | tv:us_screener |
| CLS | US | Celestica, Inc. | tv:us_screener |
| NTAP | US | NetApp, Inc. | tv:us_screener |
| VEEV | US | Veeva Systems Inc. | tv:us_screener |
| XYZ | US | Block, Inc. | tv:us_screener |
| FLEX | US | Flex Ltd. | tv:us_screener |
| RVMD | US | Revolution Medicines, Inc. | tv:us_screener,us_best |
| WAT | US | Waters Corporation | tv:us_screener |
| TWLO | US | Twilio Inc. | tv:us_screener |
| CRDO | US | Credo Technology Group Holding Ltd | tv:us_screener |
| OKTA | US | Okta, Inc. | tv:us_screener |
| UAL | US | United Airlines Holdings, Inc. | tv:us_screener |
| EL | US | Estee Lauder Companies, Inc. (The) | tv:us_screener |
| ON | US | ON Semiconductor Corporation | tv:us_screener |
| CNC | US | Centene Corporation | tv:us_screener |
| SMCI | US | Super Micro Computer, Inc. | tv:us_screener |
| MDB | US | MongoDB, Inc. | tv:us_screener |
| HPQ | US | HP Inc. | tv:us_screener |
| WSM | US | Williams-Sonoma, Inc. | tv:us_screener |
| TSEM | US | Tower Semiconductor Ltd. | tv:us_screener,us_best |
| ZM | US | Zoom Communications, Inc. | tv:us_screener |
| NVT | US | nVent Electric plc | tv:us_screener |
| CPAY | US | Corpay, Inc. | tv:us_screener |
| SN | US | SharkNinja, Inc. | tv:us_screener |
| ATI | US | ATI Inc. | tv:us_screener |
| MTSI | US | MACOM Technology Solutions Holdings, Inc. | tv:us_screener |
| RBRK | US | Rubrik, Inc. | tv:us_screener |
| ENTG | US | Entegris, Inc. | tv:us_screener |
| AFRM | US | Affirm Holdings, Inc. | tv:us_screener |
| IOT | US | Samsara Inc. | tv:us_screener |
| ROKU | US | Roku, Inc. | tv:us_screener |
| GMAB | US | Genmab A/S | tv:us_screener |
| SNX | US | TD SYNNEX Corporation | tv:us_screener |
| PTC | US | PTC Inc. | tv:us_screener |
| SITM | US | SiTime Corporation | tv:us_screener |
| U | US | Unity Software Inc. | tv:us_screener |
| SWKS | US | Skyworks Solutions, Inc. | tv:us_screener |
| LSCC | US | Lattice Semiconductor Corporation | tv:us_screener |
| SMTC | US | Semtech Corporation | tv:us_screener,us_best |
| TLN | US | Talen Energy Corporation | tv:us_screener |
| WCC | US | WESCO International, Inc. | tv:us_screener |
| TOST | US | Toast, Inc. | tv:us_screener |
| RVTY | US | Revvity, Inc. | tv:us_screener |
| XP | US | XP Inc. | tv:us_screener |
| ONTO | US | Onto Innovation Inc. | tv:us_screener |
| BMNR | US | BitMine Immersion Technologies, Inc. | tv:us_screener |
| CRL | US | Charles River Laboratories International, Inc. | tv:us_screener |
| W | US | Wayfair Inc. | tv:us_screener |
| JHX | US | James Hardie Industries plc. | tv:us_screener |
| TTMI | US | TTM Technologies, Inc. | tv:us_screener |
| GNRC | US | Generac Holdings Inc. | tv:us_screener |
| VICR | US | Vicor Corporation | tv:us_screener,us_best |
| TEM | US | Tempus AI, Inc. | tv:us_screener |
| VIAV | US | Viavi Solutions Inc. | tv:us_screener,us_best |
| HUT | US | Hut 8 Corp. | tv:us_screener |
| FORM | US | FormFactor, Inc. | tv:us_screener,us_best |
| AAOI | US | Applied Optoelectronics, Inc. | tv:us_screener,us_best |
| TWST | US | Twist Bioscience Corporation | tv:us_screener,us_best |
| TXG | US | 10x Genomics, Inc. | tv:us_screener,us_best |
| SNAP | US | Snap Inc. | tv:us_screener |
| MXL | US | MaxLinear, Inc | tv:us_screener,us_best |
| SIMO | US | Silicon Motion Technology Corporation | tv:us_screener |
| RGEN | US | Repligen Corporation | tv:us_screener |
| S | US | SentinelOne, Inc. | tv:us_screener |
| GTLB | US | GitLab Inc. | tv:us_screener |
| ZETA | US | Zeta Global Holdings Corp. | tv:us_screener |
| HNGE | US | Hinge Health, Inc. | tv:us_screener |
| HIMS | US | Hims & Hers Health, Inc. | tv:us_screener |
| CLF | US | Cleveland-Cliffs Inc. | tv:us_screener |
| ETSY | US | Etsy, Inc. | tv:us_screener |
| IOVA | US | Iovance Biotherapeutics, Inc. | tv:us_screener,us_best |
| KOD | US | Kodiak Sciences Inc | tv:us_screener,us_best |
| VSH | US | Vishay Intertechnology, Inc. | tv:us_screener |
| AXTI | US | AXT Inc | tv:us_screener,us_best |
| SYNA | US | Synaptics Incorporated | tv:us_screener |
| RXO | US | RXO, Inc. | tv:us_screener |
| MAT | US | Mattel, Inc. | tv:us_screener |
| PENG | US | Penguin Solutions, Inc. | tv:us_screener |
| AEHR | US | Aehr Test Systems | tv:us_screener,us_best |
| ASST | US | Strive, Inc. | tv:us_screener |
| RXRX | US | Recursion Pharmaceuticals, Inc. | tv:us_screener |
| ELOX | US | Eloxx Pharmaceuticals, Inc. | tv:us_best |
| MGRT | US | Mega Fortune Company Limited | tv:us_best |
| MRNA | US | Moderna, Inc. | tv:us_best |
| ERAS | US | Erasca, Inc. | tv:us_best |
| SLS | US | SELLAS Life Sciences Group, Inc. | tv:us_best |
| CLYM | US | Climb Bio, Inc. | tv:us_best |
| MTC | US | MMTec, Inc. | tv:us_best |
| TJGC | US | TJGC Group Limited | tv:us_best |
| PRAX | US | Praxis Precision Medicines, Inc. | tv:us_best |
| SYRE | US | Spyre Therapeutics, Inc. | tv:us_best |
| OPTX | US | Syntec Optics Holdings, Inc. | tv:us_best |
| EDRY | US | EuroDry Ltd. | tv:us_best |
| CYPH | US | Cypherpunk Technologies Inc. | tv:us_best |
| BUUU | US | BUUU Group Limited | tv:us_best |
| IMMX | US | Immix Biopharma, Inc. | tv:us_best |
| CDNA | US | CareDx, Inc. | tv:us_best |
| AP | US | Ampco-Pittsburgh Corporation | tv:us_best |
| VNCE | US | Vince Holding Corp. | tv:us_best |
| OMER | US | Omeros Corporation | tv:us_best |
| AGCC | US | Agencia Comercial Spirits Ltd | tv:us_best |
| ORKA | US | Oruka Therapeutics, Inc. | tv:us_best |
| IBRX | US | ImmunityBio, Inc. | tv:us_best |
| MAAS | US | Maase Inc. | tv:us_best |
| RLYB | US | Rallybio Corporation | tv:us_best |
| ANTX | US | AN2 Therapeutics, Inc. | tv:us_best |
| ANRO | US | Alto Neuroscience, Inc. | tv:us_best |
| ATEX | US | Anterix Inc. | tv:us_best |
| QTTB | US | Q32 Bio Inc. | tv:us_best |
| CHRN | US | ChronoScale Holdings Corporation | tv:us_best |
| BDSX | US | Biodesix, Inc. | tv:us_best |
| COHU | US | Cohu, Inc. | tv:us_best |
| RFAI | US | RF Acquisition Corp II | tv:us_best |
| BAND | US | Bandwidth Inc. | tv:us_best |
| SILC | US | Silicom Ltd | tv:us_best |
| OESX | US | Orion Energy Systems, Inc. | tv:us_best |
| NVCT | US | Nuvectis Pharma, Inc. | tv:us_best |
| MBX | US | MBX Biosciences, Inc. | tv:us_best |
| DOCN | US | DigitalOcean Holdings, Inc. | tv:us_best |
| MANE | US | Veradermics, Incorporated | tv:us_best |
| NUAI | US | New Era Energy & Digital, Inc. | tv:us_best |
| FET | US | Forum Energy Technologies, Inc. | tv:us_best |
| SIF | US | SIFCO Industries, Inc. | tv:us_best |
| ALTO | US | Alto Ingredients, Inc. | tv:us_best |
| RLAY | US | Relay Therapeutics, Inc. | tv:us_best |
| BFLY | US | Butterfly Network, Inc. | tv:us_best |
| CLMT | US | Calumet, Inc | tv:us_best |
| PACS | US | PACS Group, Inc. | tv:us_best |
| GLBS | US | Globus Maritime Limited | tv:us_best |
| ECO | US | Okeanis Eco Tankers Corp. | tv:us_best |
| AGL | US | agilon health, inc. | tv:us_best |
| EVC | US | Entravision Communications Corporation | tv:us_best |
| ICHR | US | Ichor Holdings | tv:us_best |
| VSXY | US | Victorias Secret & Co. | tv:us_best |
| FSLY | US | Fastly, Inc. | tv:us_best |
| DFTX | US | Definium Therapeutics, Inc. | tv:us_best |
| TNGX | US | Tango Therapeutics, Inc. | tv:us_best |
| HPE | US | Hewlett Packard Enterprise Company | tv:us_best |
| REPL | US | Replimune Group, Inc. | tv:us_best |
| HYMC | US | Hycroft Mining Holding Corporation | tv:us_best |
| LIND | US | Lindblad Expeditions Holdings Inc. | tv:us_best |
| VSTS | US | Vestis Corporation | tv:us_best |
| PURR | US | Hyperliquid Strategies Inc | tv:us_best |
| FOSL | US | Fossil Group, Inc. | tv:us_best |
| ABLV | US | Able View Global Inc. | tv:us_best |
| OABI | US | OmniAb, Inc. | tv:us_best |
| NDLS | US | Noodles & Company | tv:us_best |
| PBF | US | PBF Energy Inc. | tv:us_best |
| RNG | US | RingCentral, Inc. | tv:us_best |
| CGEM | US | Cullinan Therapeutics, Inc. | tv:us_best |
| INBX | US | Inhibrx Biosciences, Inc. | tv:us_best |
| GH | US | Guardant Health, Inc. | tv:us_best |
| ETON | US | Eton Pharmaceuticals, Inc. | tv:us_best |
| FTH | US | Faeth Therapeutics, Inc. | tv:us_best |
