# Research grounding: canary traps and catching document leakers

Fact-check notes for the Junction 2026 project in `s1laswang/agent-arena`. I opened every source linked below on **2026-11-14** with curl/WebFetch, and every quote is copied word for word from the page as fetched. Where a quote comes from an archive.org book scan, I got it through archive.org's full-text search, which returns short overlapping snippets. Those quotes are joined only where the snippets overlap word for word.

**Verdict scale (section 2):** **CONFIRMED** = a primary source (court record, official statement, the person's own post) or several independent reputable outlets · **REPORTED** = one reputable outlet, or sources that agree on the core fact but not the details · **RUMOURED/UNVERIFIED** = no primary source found, sources hedge, or the claim is only an allegation.

---

## 1. History: "canary trap" and "barium meal"

**Tom Clancy coined "canary trap" in *Patriot Games* (G.P. Putnam's Sons, New York, 1987).** The archive.org catalogue record for the first edition gives *publisher "New York : Putnam", date "1987"*, and the scanned text uses the term:
> "What the devil is this Canary Trap?" "Well, you know about all the problems CIA has with leaks.

[archive.org – Patriot Games (Putnam, 1987)](https://archive.org/details/patriotgamesclan00clan?q=%22canary+trap%22) (full-text search snippet; the second sentence is completed from Ars Technica's quote of the same passage below)

**How Clancy's Jack Ryan describes the technique** (as quoted by Ars Technica from the book):
> "Each summary paragraph has six different versions, and the mixture of those paragraphs is unique to each numbered copy of the paper. There are over a thousand possible permutations, but only ninety-six numbered copies of the actual document. … If he quotes something from two or three of those paragraphs, we know which copy he saw and, therefore, who leaked it."

[Ars Technica, 4 May 2026](https://arstechnica.com/tech-policy/2026/05/in-canada-a-canary-trap-springs-shut-and-ids-election-database-leak/). The book scan matches: *"can do it by computer. You use a thesaurus program to shuffle through synonyms, and you"*. [archive.org – Patriot Games](https://archive.org/details/patriotgamesclan00clan?q=%22thesaurus+program%22)

**Clancy named the technique but did not invent it.** Wikipedia (used only as a pointer):
> "The term was coined by Tom Clancy in his 1987 novel Patriot Games, although Clancy did not invent the technique."

[Wikipedia – Canary trap](https://en.wikipedia.org/wiki/Canary_trap)

**MI5's "barium meal": Peter Wright, *Spycatcher* (1987).** Wright describes MI5 feeding a suspected leak a piece of bait:
> "We decided to feed what is known in the business as a 'barium meal,' in other words, offer a bait of sufficiently important intelligence that the two-legged source, if he existed, would have to relay it back to the Russians."

[New York Magazine / Intelligencer, 9 Oct 2019, quoting Spycatcher](https://nymag.com/intelligencer/2019/10/coleen-rooney-rebekah-vardy-and-the-canary-trap.html). I checked this against the 1987 scan (William Heinemann Australia, 1987): *"feed what is known in the business as a "barium meal," in other words, offer a bait of sufficiently important intelligence that the two- legged source, if he existed, would have to relay it back to the Russians."* The same scan also has *"More barium-meal tests were done to try to locate the"* and *"I arranged to feed him barium meals."* [archive.org – Spycatcher (1987)](https://archive.org/details/spycatcher00wrig?q=barium)

- Pitch nuance: Wright's barium meal is **bait** (one secret fed to one suspect, then watching whether it reaches the other side). Clancy's canary trap is **per-recipient document variants**. Both rest on the same idea: give each suspect something unique and see which version surfaces.

**Related claim: Thatcher's word-spacing watermark is RUMOURED.** Cambridge security researchers repeat the story but hedge it with "Apparently":
> "Apparently, during the 1980's, Margaret Thatcher became so irritated at press leaks of cabinet documents that she had the word processors programmed to encode their identity in the word spacing, so that disloyal ministers could be traced."

[Anderson & Petitcolas, "On the Limits of Steganography", IEEE JSAC 16(4), 1998](https://www.cl.cam.ac.uk/~rja14/Papers/jsac98-limsteg.pdf). A steganography textbook states it with no hedge: *"Thatcher ordered that the word processors being used by government employees encode their identity in the word spacing of the document."* [Investigator's Guide to Steganography (flylib copy)](https://flylib.com/books/en/1.496.1.45/1/). I found no primary source (government record, minister, or official). The Thatcher Foundation's "Leak procedures" record that I opened ([margaretthatcher.org/document/151895](https://www.margaretthatcher.org/document/151895)) does not mention it. **Treat as folklore.**

---

## 2. Real cases of leak hunting with uniquely marked documents or data

### 2a. Tesla / Elon Musk

**(i) The June 2018 "saboteur" email: CONFIRMED that it was sent. No evidence that marked documents were used.**
> "I was dismayed to learn this weekend about a Tesla employee who had conducted quite extensive and damaging sabotage to our operations. This included making direct code changes to the Tesla Manufacturing Operating System under false usernames and exporting large amounts of highly sensitive Tesla data to unknown third parties."

[CNBC, 18 Jun 2018 (full email; "Several employees, from different divisions within Tesla, confirmed receipt of the e-mail to CNBC")](https://www.cnbc.com/2018/06/18/elon-musk-email-employee-conducted-extensive-and-damaging-sabotage.html)

Tesla then sued the employee, Martin Tripp:
> "he has thus far admitted to writing software that hacked Tesla's manufacturing operating system ("MOS") and to transferring several gigabytes of Tesla data to outside entities."

[Tesla, Inc. v. Tripp, Complaint, D. Nev. No. 3:18-cv-00296 (CourtListener)](https://storage.courtlistener.com/recap/gov.uscourts.nvd.131251/gov.uscourts.nvd.131251.1.0_1.pdf)

**How Tesla actually found Tripp (sworn testimony): access attribution plus audit logs, not a canary trap.** Tesla's Senior Manager of Global Security testified:
> "we found a Tableau chart that populated the details for that data, we went into the audit logs for that Tableau chart, we looked to see who had accessed that chart, the exact time and date when the figure on that chart equaled the figure on -- within Ms. Lopez's article, and the only individual who accessed the chart at that time was Martin Tripp."

[Gicinto deposition excerpts, 27 Aug 2019, ECF 113-1](https://storage.courtlistener.com/recap/gov.uscourts.nvd.131279/gov.uscourts.nvd.131279.113.1.pdf)
- Pitch angle: the real-time chart worked like an **accidental canary**, because each moment's figure was unique ("if you deviated even 30 seconds either way, you would get a different figure"). Still, **nothing shows Tesla marked documents in 2018.** Any claim that "Tesla caught the 2018 saboteur with a canary trap" is **unsupported**.

**(ii) Musk's own description of the 2008 trap: CONFIRMED that he posted it.** On 9 Oct 2022 (13:30 UTC, 15:30 Helsinki time) a user asked how Tesla caught "that employee who leaked the confidential data of Tesla … in 2008". Musk replied:
> "That is quite an interesting story. We sent what appeared to be identical emails to all, but each was actually coded with either one or two spaces between sentences, forming a binary signature that identified the leaker."

[X post by @elonmusk, status 1579101966453858305](https://x.com/elonmusk/status/1579101966453858305). The text comes from X's public embed endpoint ([syndication JSON](https://cdn.syndication.twimg.com/tweet-result?id=1579101966453858305&token=a)), which also shows the parent question. The same wording appears in [The Economic Times, 9 Oct 2022](https://economictimes.indiatimes.com/news/international/world-news/elon-musk-reveals-to-indian-follower-how-tesla-caught-employee-who-leaked-data-in-2008/articleshow/94744879.cms) and [The Intercept, 15 Dec 2022](https://theintercept.com/2022/12/15/elon-musk-leaks-twitter/).

**(iii) A contemporaneous 2009 report of a varied-email trap at Tesla: REPORTED (one outlet, anonymous tipster).** Gawker/Valleywag, 4 Mar 2009:
> "Musk set out to entrap potential leakers by sending each employee a slightly altered version of an email which he expected would get sent to the media."
> "By altering phrases scattered throughout the email — changing "I'm" to "I am," for example — a Tesla IT employee created individualized memos which would have a detectable "fingerprint" in the text."

The same article says the trap **backfired**:
> "Hapless general counsel Craig Harding … forwarded his own personalized copy along with the agreement. As a result, everyone at Tesla had a copy of Harding's version to compare to their own, making Musk's scheme plain to see — and giving them a version that was safe to leak."

[Gawker (archived), "Tesla CEO in Digital Witch Hunt"](https://web.archive.org/web/20131020092330/http://gawker.com/5164035/tesla-ceo-in-digital-witch-hunt)

**Overall verdict on "Musk caught the 2008 leaker with uniquely spaced emails": DISPUTED/UNVERIFIED.** The accounts disagree:
- Gawker says the 2008 leaker (Peng Zhou) was identified **before** the trap, through forensics: *"He hired an outside IT contractor go through the company's email and instant messages, and then had an investigator take fingerprints off a printout discarded near a copier"*. It describes the trap as a later attempt that failed. It also says the variants used wording changes, not spaces. ([Gawker](https://web.archive.org/web/20131020092330/http://gawker.com/5164035/tesla-ceo-in-digital-witch-hunt))
- The Intercept notes a third version, from Ashlee Vance's 2015 biography: *"Vance states that Musk retyped the letter into a Word document, printed it, and then looked through printer logs to find who else had printed a document of the same size."* ([The Intercept](https://theintercept.com/2022/12/15/elon-musk-leaks-twitter/)). I did not open the Vance book; this is attributed via The Intercept.
- **Safe pitch wording:** "Musk has publicly claimed Tesla used per-recipient whitespace fingerprints to catch a leaker (X, Oct 2022). A 2009 Gawker report describes a similar varied-wording trap at Tesla that backfired."

### 2b. Other cases

| Case | What was marked | Verdict | Evidence |
|---|---|---|---|
| **Elections Alberta, 2026**: voter list leaked to the separatist Centurion Project | Fake "salted" elector entries, unique per recipient | **CONFIRMED** (official statement + CBC + Ars) | Elections Alberta: *"Specific security features are added to each list provided to eligible recipients allowing Elections Alberta to identify who received each specific copy of the list."* [elections.ab.ca](https://www.elections.ab.ca/resources/media/news-releases/update-unauthorized-use-of-list-of-electors/) · CBC, 15 May 2026: *"These fictional identities are embedded in the list to help investigators trace each dataset to their source. A name was found matching a list legitimately provided to the pro-independence Republican Party of Alberta in June 2025. Another 86 fictional identities were found."* [CBC](https://www.cbc.ca/news/canada/edmonton/court-documents-voter-list-9.7201375) · Ars: *"they salt it with additional but bogus entries. The fake entries inserted in the Republican Party version of the list showed up in Centurion's online tool, too."* [Ars Technica](https://arstechnica.com/tech-policy/2026/05/in-canada-a-canary-trap-springs-shut-and-ids-election-database-leak/) |
| **"Wagatha Christie", 2019**: Coleen Rooney vs Rebekah Vardy | Fake Instagram stories visible to only one account (audience-restricted bait, not a marked document) | **CONFIRMED** (High Court judgment) | Rooney's post as reproduced in the judgment: *"I blocked everyone from viewing my Instagram stories except ONE account."* Court: *"I have found that Ms Vardy was party to the disclosure to [The Sun] of the … Gender Selection and Flooded Basement Posts"* and *"the claim is dismissed."* [Vardy v Rooney [2022] EWHC 2017 (QB)](https://caselaw.nationalarchives.gov.uk/ewhc/qb/2022/2017) |
| **UK Conservative whips, Dec 2020**: Andrew Lewer MP sacked as PPS | Chief whip's letter worded differently for each recipient | **REPORTED** (Guardian, attributed only as "it is understood"; Lewer denied leaking) | *"it is understood that the letter, from the chief whip, Mark Spencer, was worded slightly differently for each recipient so officials would be able to tell which version had reached the media."* [The Guardian, 18 Dec 2020](https://www.theguardian.com/politics/2020/dec/18/ministerial-aide-sacked-after-leaking-of-letter-warning-mps-not-to-leak-to-media-andrew-lewer) |
| **NBA, about 2010**: Pistons executive Joe Dumars fined | League memos varied per team | **REPORTED** (Business Insider, relaying Kevin Draper of The New Republic) | *"each team would get a slightly different version in which a few words or numbers would be changed."* [Business Insider, 18 Dec 2014](https://www.businessinsider.com/nba-canary-trap-media-2014-12) |
| **Apple, 2023**: leaker "@analyst941" | Different false release dates given to different employees | **REPORTED** (Macworld; based on the leaker's own farewell post; Apple did not confirm) | *"The combination of release dates they posted–Final Cut Pro coming in 2024 and Logic in 2025–was unique to his sister, and the source of the leaks thus identified."* Macworld adds: *"we'll probably never know if this story is true either."* [Macworld, 11 May 2023](https://www.macworld.com/article/1816449/leaker-analyst941-twitter-busted-apple-sting-operation.html) |
| **Star Trek III script, about 1983** (Harve Bennett) | Numbered script copies | **REPORTED** (one biography) | *"clue and matched the number to his master distribution list. It had been Roddenberry's copy."* [Engel, *Gene Roddenberry: The Myth and the Man* (1994), archive.org](https://archive.org/details/generoddenberrym00enge?q=%22master+distribution+list%22) |
| **Steve Jobs's fake "Asteroid" product** | Different details fed to different people | **UNVERIFIED** (one passing line in Business Insider, no sourcing) | *"Steve Jobs used a version of the "canary trap" by making up a product called "Asteroid""* [Business Insider](https://www.businessinsider.com/nba-canary-trap-media-2014-12) |
| **MI6 vetting "barium meal", 2025** | Only the vetting form linked a candidate's alias accounts | **UNVERIFIED** (a complainant's allegation to the Investigatory Powers Tribunal) | *"In intelligence circles, this kind of situation is what they'd call a 'barium meal'."* [Computer Weekly, 25 Mar 2025](https://www.computerweekly.com/news/366620867/Tech-specialist-files-legal-claim-after-being-refused-security-clearance-for-MI6-role) |

**Reality Winner / The Intercept, 2017: not a canary trap.** The printer tracking dots (machine identification code) were real, but the FBI affidavit credits print and email audits:
- Dots exist: *"The document leaked by the Intercept was from a printer with model number 54, serial number 29535218. The document was printed on May 9, 2017 at 6:20."* [Errata Security](https://blog.erratasec.com/2017/06/how-intercept-outed-reality-winner.html)
- How Winner was actually identified: *"The U.S. Government Agency determined that six individuals printed this reporting. WINNER was one of these six individuals. A further audit of the six individuals' desk computers revealed that WINNER had e-mail contact with the News Outlet."* [FBI affidavit (Courthouse News copy)](https://www.courthousenews.com/wp-content/uploads/2017/06/WINNER-COMPLAINT-AFFIDAVIT.pdf)
- EFF: *"The affidavit did not mention the use of the tracking dots at all … It's quite possible that printer dots did not play any role in this investigation at all."* [EFF, June 2017](https://www.eff.org/deeplinks/2017/06/printer-tracking-dots-back-news)
- **Verdict:** the dots are CONFIRMED. That the dots caught her is **UNVERIFIED**, and the official record points to audit logs. Present this as forensic watermarking that every colour laser printer adds (not a deliberate per-recipient canary), plus classic access auditing.

---

## 3. Insider-threat statistics (latest editions)

**Ponemon Institute / DTEX, *2026 Cost of Insider Risks Global Report*** (fieldwork ended Sep 2025; data is for FY2025)
- Annual cost: *"Insider risk now costs organizations an average of US$19.5M annually, driven primarily by negligent, non-malicious behavior"* [DTEX report page](https://ponemon.dtex.ai/)
- Frequency and sample: *"Since the 2018 study, the number of organizations represented in the research has more than doubled from 156 to 354 in 2025 and the average number of incidents discovered and analyzed in this research increased from 3,269 to 7,490 in 2025."* [Ponemon Institute blog](https://www.ponemon.org/news-updates/blog/security/lessons-learned-from-the-2026-global-cost-of-insider-risks.html). The report table gives *"Average number of insider risk incidents per organization … 25.4"* for FY2025 ([report PDF, copy hosted by cinrmcoe-cdecgrin.ca](https://www.cinrmcoe-cdecgrin.ca/_files/ugd/026a5a_c7b8bd224389449ba499ff8e7e2c37c9.pdf); DTEX's own download is behind a form).
- Time to contain: *"the average time to contain the incident decreased significantly in 2025 to 67 days from 81 days in 2024, only 13 percent of incidents were contained in less than 30 days."* [Ponemon blog](https://www.ponemon.org/news-updates/blog/security/lessons-learned-from-the-2026-global-cost-of-insider-risks.html). The figure is 86 days in 2023: *"average containment time has dropped from 86 days in 2023 to 67 days in 2025"* [report PDF](https://www.cinrmcoe-cdecgrin.ca/_files/ugd/026a5a_c7b8bd224389449ba499ff8e7e2c37c9.pdf). Caveat: the report calls both drops "17%", but 81 to 67 is about 17% and 86 to 67 is about 22%.
- Cost by speed: *"If it takes more than 90 days, the average cost is $21.9 million. If it takes less than 30 days, the average cost is $14.2 million."* [Ponemon blog](https://www.ponemon.org/news-updates/blog/security/lessons-learned-from-the-2026-global-cost-of-insider-risks.html)
- Malicious insiders specifically: *"Malicious insiders accounted for an average of 6.3 incidents and the average cost per incident of $742,125."* (same source)
- Caveat for the pitch: the sample is *"354 … Organizations that experienced one or more material events caused by an insider"* ([report PDF](https://www.cinrmcoe-cdecgrin.ca/_files/ugd/026a5a_c7b8bd224389449ba499ff8e7e2c37c9.pdf)). These are averages over affected organisations, not all companies, and the survey is vendor-sponsored.

**Verizon, *2026 Data Breach Investigations Report*** (19th edition; incidents from 1 Nov 2024 to 31 Oct 2025)
- Scale: *"we dig into more than 31,000 actual real-world security incidents, of which more than 22,000 were confirmed data breaches involving organizations in 145 countries."* [2026 DBIR Executive Summary (PDF)](https://www.verizon.com/business/resources/executivebriefs/2026-dbir-executive-summary.pdf)
- Privilege Misuse pattern, from the cover chart: *"2026 … 3% Privilege Misuse"*, compared with *"2025 … 7% Privilege Misuse"* and 8% in 2024. (same PDF)
- Insider action: *"Shadow AI is now the third most common non-malicious insider action detected in our data loss prevention (DLP) dataset in 2025, a fourfold increase in percentage from the previous year."* (same PDF)
- Internal actors by sector: Public Administration *"External (56%), Internal (44%) (breaches)"*; Healthcare *"External (81%), Internal (19%)"*; Education *"External (78%), Internal (22%)"*. (same PDF)
- **Unverified:** the headline figure "internal actors in 12% of all breaches (down from 18%)" appears only in secondary write-ups. The full 2026 report sits behind a form and the overall split is not in the executive summary I opened. **Do not cite 12% without opening the full report.**
- Edition and dates: [DBIR landing page](https://www.verizon.com/business/resources/reports/dbir/): *"the incidents described in the 2026 edition took place between November 1, 2024, and October 31, 2025."*

**CISA: definition (no statistics on the page)**
> "CISA defines insider threat as the threat that an insider will use their authorized access, wittingly or unwittingly, to do harm to the department's mission, resources, personnel, facilities, information, equipment, networks, or systems."

> "Their actions can include leaking sensitive information, harassing associates, sabotaging equipment, perpetrating violence, or stealing proprietary data or intellectual property"

[CISA – Defining Insider Threats](https://www.cisa.gov/topics/physical-security/insider-threat-mitigation/defining-insider-threats)

**CMU SEI CERT (National Insider Threat Center)**
> "We have a database of over 3,000 insider incidents that we use to characterize the nature of the evolving insider threat problem"

> "Since 2001, we have partnered with government agencies—such as the Department of War, the Department of Homeland Security, Secret Service, and many federal agencies"

[SEI – Insider Threat](https://www.sei.cmu.edu/insider-threat/)

---

## 4. CMU CERT Insider Threat Test Dataset

- **What it is:** synthetic data, not real employee logs. *"The Insider Threat Test Dataset is a collection of synthetic insider threat test datasets that provide both background and malicious actor synthetic data."* [SEI dataset page](https://www.sei.cmu.edu/library/insider-threat-test-dataset/)
- **Who made it:** *"The CERT Division, in partnership with ExactData, LLC, and under sponsorship from DARPA I2O, generated a collection of synthetic insider threat test datasets."* (same page). The KiltHub record lists author *Brian Lindauer* and funding *"DARPA FA8721-05-C-0003"*.
- **Releases:** the files on the record are `r1`, `r2`, `r3.1`, `r3.2`, `r4.1`, `r4.2`, `r5.1`, `r5.2`, `r6.1`, `r6.2` (`.tar.bz2`), plus `answers.tar.bz2`. The record says *"Most releases include multiple datasets (e.g., r3.1 and r3.2). Generally, later releases include a superset of the data generation functionality of earlier releases."* and *"The answer key file answers.tar.bz2 contains the details of the malicious activity included in each dataset, including descriptions of the scenarios enacted and the identifiers of the synthetic users involved."* Sizes range from about 88 MB (r1) to about 24 GB (r6.2) compressed.
- **Licence: CC BY 4.0.** The record's metadata reads `"license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}`. Its "Copyright Statement" field is empty, and I found no separate terms of use. [figshare API record 12841247](https://api.figshare.com/v2/articles/12841247)
- **Canonical link and DOI:** https://doi.org/10.1184/R1/12841247.v1 redirects (HTTP 302) to `https://kilthub.cmu.edu/articles/dataset/Insider_Threat_Test_Dataset/12841247/1`. The SEI page says: *"The datasets are available for download from https://doi.org/10.1184/R1/12841247.v1."* Note: the KiltHub HTML page and the README file download returned **403** to automated fetches. Licence and citation come from the official figshare API and the DOI metadata for the same record.
- **Citation (as given in the record):** *"Lindauer, Brian (2020). Insider Threat Test Dataset. Carnegie Mellon University. Dataset. https://doi.org/10.1184/R1/12841247.v1"*. The record also links the background paper: Glasser & Lindauer, *"Bridging the Gap: A Pragmatic Approach to Generating Insider Threat Data"*, IEEE S&P Workshops 2013, [doi:10.1109/SPW.2013.37](https://doi.org/10.1109/SPW.2013.37).
- **Fit for this project:** the data simulates host logs (logons, devices, files, email, web) with labelled malicious-insider scenarios. It contains **no per-recipient document variants**, so it can serve as a behavioural baseline or test harness, but a canary-trap evaluation needs synthetic marked documents generated on top of it. (This is my inference from the description, not a quote.)

---

## Confirmed vs rumoured: summary

| Claim | Verdict |
|---|---|
| Clancy coined "canary trap" in *Patriot Games* (Putnam, 1987) | **CONFIRMED** |
| MI5 "barium meal" described in Wright's *Spycatcher* (1987) | **CONFIRMED** |
| Thatcher had word processors encode user identity in word spacing | **RUMOURED** (hedged as "Apparently", no primary source) |
| Musk's June 2018 all-staff "saboteur" email | **CONFIRMED** |
| Tesla used marked documents to catch the 2018 saboteur (Tripp) | **NOT SUPPORTED**: sworn testimony describes access attribution and Tableau audit logs |
| Musk posted (Oct 2022) that Tesla used one/two-space binary-coded emails to catch a 2008 leaker | **CONFIRMED** that he said it |
| That the whitespace trap actually caught the 2008 leaker | **DISPUTED/UNVERIFIED** (Gawker 2009: fingerprints/IT forensics, and a varied-wording trap that backfired; Vance via The Intercept: printer logs) |
| Tesla attempted a varied-wording email trap around 2009 | **REPORTED** (Gawker tipster; consistent with Musk's later claim) |
| Elections Alberta salted voter lists traced a 2026 leak | **CONFIRMED** |
| Coleen Rooney's Instagram bait (Wagatha Christie) | **CONFIRMED** (High Court) |
| UK chief whip's per-recipient letter, Lewer sacked (2020) | **REPORTED** |
| NBA per-team memo variants (Dumars) | **REPORTED** |
| Apple 2023 per-employee fake release dates | **REPORTED** (leaker's own account) |
| Star Trek III numbered scripts traced to Roddenberry | **REPORTED** |
| Steve Jobs "Asteroid" fake product | **UNVERIFIED** |
| MI6 vetting barium meal (2025) | **UNVERIFIED** (allegation) |
| Reality Winner caught by printer dots | **UNVERIFIED**: the dots existed, but the affidavit cites print and email audits |
| Insider risk costs US$19.5M per affected org per year; 25.4 incidents; 67 days to contain (Ponemon/DTEX 2026) | **CONFIRMED** (vendor-sponsored survey) |
| DBIR 2026: Privilege Misuse 3% of breaches; Public Admin 44% internal | **CONFIRMED** (exec summary) |
| DBIR 2026: internal actors in 12% of all breaches | **UNVERIFIED** (full report gated) |
| CERT dataset is synthetic, r1–r6.2, CC BY 4.0, DOI 10.1184/R1/12841247.v1 | **CONFIRMED** |

## Sources opened (all accessed 2026-11-14)

1. https://en.wikipedia.org/wiki/Canary_trap (pointer only)
2. https://archive.org/details/patriotgamesclan00clan (+ archive.org full-text search API)
3. https://arstechnica.com/tech-policy/2026/05/in-canada-a-canary-trap-springs-shut-and-ids-election-database-leak/
4. https://archive.org/details/spycatcher00wrig (+ full-text search API)
5. https://nymag.com/intelligencer/2019/10/coleen-rooney-rebekah-vardy-and-the-canary-trap.html
6. https://www.cl.cam.ac.uk/~rja14/Papers/jsac98-limsteg.pdf
7. https://flylib.com/books/en/1.496.1.45/1/
8. https://www.margaretthatcher.org/document/151895
9. https://www.cnbc.com/2018/06/18/elon-musk-email-employee-conducted-extensive-and-damaging-sabotage.html
10. https://storage.courtlistener.com/recap/gov.uscourts.nvd.131251/gov.uscourts.nvd.131251.1.0_1.pdf
11. https://storage.courtlistener.com/recap/gov.uscourts.nvd.131279/gov.uscourts.nvd.131279.113.1.pdf
12. https://x.com/elonmusk/status/1579101966453858305 and https://cdn.syndication.twimg.com/tweet-result?id=1579101966453858305&token=a
13. https://economictimes.indiatimes.com/news/international/world-news/elon-musk-reveals-to-indian-follower-how-tesla-caught-employee-who-leaked-data-in-2008/articleshow/94744879.cms
14. https://theintercept.com/2022/12/15/elon-musk-leaks-twitter/
15. https://web.archive.org/web/20131020092330/http://gawker.com/5164035/tesla-ceo-in-digital-witch-hunt
16. https://www.elections.ab.ca/resources/media/news-releases/update-unauthorized-use-of-list-of-electors/
17. https://www.cbc.ca/news/canada/edmonton/court-documents-voter-list-9.7201375
18. https://caselaw.nationalarchives.gov.uk/ewhc/qb/2022/2017
19. https://www.theguardian.com/politics/2020/dec/18/ministerial-aide-sacked-after-leaking-of-letter-warning-mps-not-to-leak-to-media-andrew-lewer
20. https://www.businessinsider.com/nba-canary-trap-media-2014-12
21. https://www.macworld.com/article/1816449/leaker-analyst941-twitter-busted-apple-sting-operation.html
22. https://archive.org/details/generoddenberrym00enge (+ full-text search API)
23. https://www.computerweekly.com/news/366620867/Tech-specialist-files-legal-claim-after-being-refused-security-clearance-for-MI6-role
24. https://blog.erratasec.com/2017/06/how-intercept-outed-reality-winner.html
25. https://www.courthousenews.com/wp-content/uploads/2017/06/WINNER-COMPLAINT-AFFIDAVIT.pdf
26. https://www.eff.org/deeplinks/2017/06/printer-tracking-dots-back-news
27. https://ponemon.dtex.ai/
28. https://www.ponemon.org/news-updates/blog/security/lessons-learned-from-the-2026-global-cost-of-insider-risks.html
29. https://www.cinrmcoe-cdecgrin.ca/_files/ugd/026a5a_c7b8bd224389449ba499ff8e7e2c37c9.pdf
30. https://www.verizon.com/business/resources/reports/dbir/
31. https://www.verizon.com/business/resources/executivebriefs/2026-dbir-executive-summary.pdf
32. https://www.cisa.gov/topics/physical-security/insider-threat-mitigation/defining-insider-threats
33. https://www.sei.cmu.edu/insider-threat/
34. https://www.sei.cmu.edu/library/insider-threat-test-dataset/
35. https://api.figshare.com/v2/articles/12841247 and https://doi.org/10.1184/R1/12841247.v1

**Tried and failed:** KiltHub HTML page and figshare README download (403); the full DBIR 2026 PDF (behind a form); the GlobeNewswire DTEX press release (403); radiofree.org (timeout, but its source article on The Intercept was opened instead).
