# 재번역/축약 필요 행 목록

원본 Excel: `translation_1_with_entry.xlsx` (자동 생성: report_issues.py)

## 1. LLM 쓰레기 번역 — 15행 (패치 시 자동 스킵, 게임에선 일본어로 표시)

| 시트 | 행 | 파일 | 원문(앞 50자) | 현재 번역 |
|---|---|---|---|---|
| all(共通シーン) | 1119 | all\all_omi_01.scb | 「当店で扱っているナムキャラは、岩手県の担当団員で、⏎神主見習いの『うしわらさん』です！」 | 「 is shorter and sounds⏎more like a specific⏎in-game term, w |
| all(共通シーン) | 1145 | all\all_omi_01.scb | 「当店で扱っているナムキャラは、新潟県の担当団員で、⏎田園コンサルタントの『こめかまくん』です！」 | 』「 -> I need to use⏎Korean quotation marks.⏎Single quotes ar |
| all(共通シーン) | 2307 | all\all_w25_01_02.scb | 黄色い声 | THOUGHT: The user wants me⏎to act as a localization⏎translat |
| chi(如月千早) | 4114 | chi\chi_w32_02.scb | 「わかりました。では、その勝負、受けて立ちます。⏎……私達の、誇りをかけて」 | 「Okay, let's break this⏎down for a natural and⏎consistent ga |
| har(天海春香) | 3057 | har\har_scs_05.scb | 「うん！　それじゃ、亜美は、あっちに行くから、⏎兄ちゃんは、そっちをさがしてね。よろーっ！」 | 「！" (yoroshiku！) - no,⏎this isnot a⏎common Korean exclamatio |
| har(天海春香) | 3926 | har\har_w55_06.scb | 「……俺も、皆が、頑張ってくれたから、⏎１年間、支え続けられたんだと思う」 | 「: Producer⏎supports idols)」 |
| mak(菊地真) | 434 | mak\mak_cnr_a02.scb | 「じゃじゃーん、昨日、学校の実習で作った、⏎ボクの手作りケーキですっ！」 | 「the original⏎line's flow:」 |
| mak(菊地真) | 4499 | mak\mak_w55_06.scb | 「別に、お互いに嫌ってるわけじゃないんですよね。⏎ただ皆、自分のこだわりがあるだけで……」 | 「 for 」別に「): 」딱히 서로 싫어하는⏎건 아니잖아요.「 (This is a⏎commonway to⏎t |
| mik(星井美希) | 2281 | mik\mik_ni_01.scb | ラブラブミサイル！ | THOUGHT: |
| mik(星井美希) | 4311 | mik\mik_w55_09.scb | （……これで、俺の仕事も、完全に一段落だな。⏎、そして美希が、これから……） | )` if I need to represent⏎the placeholder. Given⏎the instruc |
| tak(四条貴音) | 1764 | tak\tak_cto_c01.scb | 「え？　さっきのが掛詞だったのか！？⏎どういうことだ？」 | 「" (double meaning) - a⏎bit too formal.」 |
| tak(四条貴音) | 4427 | tak\tak_w21_04.scb | ？？？ | ` (Unknown) or `？？？`⏎(literal). |
| ryu(Jupiter) | 238 | ryu\ryu_w01_01.scb | 「そーなの？　ま、なんでもいいよ、楽しそうっぽいし。⏎亜美、メッチャやる気ありまくりだよーっ！」 | 「 is a common way to⏎express 」super motivated"i⏎n a⏎casual,  |
| ryu(Jupiter) | 261 | ryu\ryu_w01_02.scb | 仌 | (No input provided, so⏎Icannot generate a⏎translation.Please |
| yay(高槻やよい) | 2083 | yay\yay_ni_01.scb | 甆 | (Waiting for Japanese text⏎to translate) |

## 2. 재줄바꿈 후 3줄 초과 — 11행 (게임에서 잘릴 수 있음, 축약 필요)

| 시트 | 행 | 파일 | 줄수 | 번역(앞 60자) |
|---|---|---|---|---|
| all(共通シーン) | 472 | all\all_kur_04.scb | 40 | 「으… 으아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아 |
| mak(菊地真) | 268 | mak\mak_clo_c01.scb | 40 | 「……뭐, 뭐어어어어어어어어어어어어어어어어어어어⏎어어어어어어어어어어어어어어어어어어어어어어어어어어⏎어어어어어어 |
| mak(菊地真) | 2030 | mak\mak_mo_01.scb | 4 | ) or 「좋죠！」 (slightly more⏎direct agreement⏎seeking). Given t |
| mak(菊地真) | 2694 | mak\mak_ni_01.scb | 4 | 하다「 (admirable, clever,⏎ingenious) or 」기가 막히다「⏎(amazing, inc |
| mak(菊地真) | 2849 | mak\mak_scr_01.scb | 40 | 「하아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아 |
| mam(双海真美) | 3282 | mam\mam_scs_05.scb | 40 | 「뭐……！ 뭐, 뭐, 뭐, 뭐, 뭐, 뭐, 뭐,⏎뭐, 뭐, 뭐, 뭐, 뭐, 뭐, 뭐, 뭐, 뭐,⏎뭐, 뭐,  |
| mik(星井美希) | 151 | mik\mik_clo_b02.scb | 40 | 「만졌어？！ ……뭐, 뭐어어어어어어어어어어어어어⏎어어어어어어어어어어어어어어어어어어어어어어어어어어⏎어어어어어어 |
| tak(四条貴音) | 362 | tak\tak_clo_c01.scb | 41 | 「아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아아아 |
| tak(四条貴音) | 5243 | tak\tak_w60_03.scb | 40 | 「사, 사, 사, 사, 사, 사, 사, 사,⏎사,사, 사, 사, 사, 사, 사, 사,⏎사, 사,사, 사, 사 |
| ryu(Jupiter) | 2199 | ryu\ryu_w03_03.scb | 40 | 「다아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아아아아아아아아아아아아아아아아아아아아아⏎아아아아아아 |
| yuk(萩原雪歩) | 3437 | yuk\yuk_scs_02.scb | 4 | 「2, 3, 5, 7, 11, 13, 17,⏎19,⏎23,29, 31, 37… 41, 43,⏎47, 53…」 |
