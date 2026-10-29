# Learning-page research

Researched: 2026-10-28. These are design candidates, not an approved redesign or evidence that SpeakLab itself improves learning.

## Evidence and possible applications

| Method | What the research supports | SpeakLab application to evaluate |
| --- | --- | --- |
| Retrieval practice | A classroom meta-analysis combined 222 studies and found benefits from testing over comparison activities; outcomes depended on practice and feedback design. | After teaching a concept, hide the notes and ask for a brief explanation before showing a reference answer. |
| Self-explanation | A meta-analysis of 64 reports found benefits from prompting learners to reason about causal and conceptual relationships. | Ask why a mechanism works or how two steps connect, rather than only asking for a definition. |
| Worked examples | Sweller and Cooper found advantages for novice algebra learners studying worked examples, particularly on structurally similar problems. | Walk through one concrete technical scenario with named steps, then ask the learner to explain a related scenario. Transfer to technical speaking is a design hypothesis. |
| Prerequisite pre-training | Experiments with narrated mechanical-system animations found benefits from introducing component knowledge before the complete mechanism. | Briefly establish unfamiliar terms and their roles before teaching interactions; allow optional background and skipping when already understood. |
| Meaningful segmentation | A meta-analysis of 56 multimedia investigations found retention/transfer benefits and reduced load, but increased learning time. | One coherent learning goal per step, learner-controlled pace and connected explanations. This does not establish an ideal card length or validate chopping prose into arbitrary screens. |
| Informative feedback | A meta-analysis of 435 studies found heterogeneous effects, with information content an important moderator. | Explain what was accurate, identify one consequential gap, provide a grounded correction and allow a retry. Model grading still needs calibration. |
| Distributed practice | A synthesis of 317 experiments found spacing effects; useful intervals depend on how long knowledge must be retained. | Bring concepts back on later days and assess unaided recall before showing notes. There is no universally optimal fixed schedule. |

## Primary research and original syntheses

- Yang et al. (2021), classroom retrieval-practice meta-analysis: https://pubmed.ncbi.nlm.nih.gov/33683913/
- Karpicke & Blunt (2011), retrieval and conceptual inference: https://pubmed.ncbi.nlm.nih.gov/21252317/
- Bisra et al. (2018), self-explanation meta-analysis: https://doi.org/10.1007/s10648-018-9434-x
- Sweller & Cooper (1985), worked-example experiments: https://doi.org/10.1207/s1532690xci0201_3
- Mayer, Mathias & Wetzell (2002), prerequisite pre-training: https://pubmed.ncbi.nlm.nih.gov/12240927/
- Rey et al. (2019), segmentation meta-analysis: https://doi.org/10.1007/s10648-018-9456-4
- Wisniewski et al. (2020), feedback meta-analysis: https://pubmed.ncbi.nlm.nih.gov/32038429/
- Cepeda et al. (2006), spacing meta-analysis: https://digitalcommons.usf.edu/psy_facpub/1771/

Programming-specific context: Margulieux, Morrison & Decker (2020) found improved formative quizzes and fewer failures/withdrawals with subgoal-labeled examples, but no improvement in average exam scores. This is not evidence of universal gains: https://doi.org/10.1186/s40594-020-00222-7

Interleaving is conditional rather than a universal recommendation: Brunmair & Richter (2019) found benefits varied by material, with ambiguous results for expository text. Contrast/application checks for related concepts are a candidate; random topic switching is not justified: https://pubmed.ncbi.nlm.nih.gov/31556629/

## AI tutor implications

Kestin et al. (2025) found improved immediate outcomes with a purpose-built tutor in undergraduate physics. Its design included a controlled activity sequence and expert-provided solutions: https://doi.org/10.1038/s41598-025-97652-6

Bastani et al. (2025) found that unrestricted GPT assistance in high-school mathematics improved supported practice but harmed subsequent unaided performance; teacher-designed hints largely mitigated that harm: https://pmc.ncbi.nlm.nih.gov/articles/PMC12232635/

These are different settings and do not establish outcomes for SpeakLab, adult CS practice or small local models. Candidate design: control objectives, prerequisites and reference answers; use the model for scoped explanations, hints and feedback; measure learning without the tutor present. Do not infer mastery from a fluent model-assisted answer.

## Candidate interaction

Keep the unprepared first recording. For selected gaps:

1. State one learning objective and establish any missing background.
2. Explain the mechanism through a concrete worked example.
3. Hide the reference and request a short causal explanation.
4. Give specific, grounded feedback; offer a hint or background bridge when needed.
5. Apply the idea to a changed scenario, then connect it back to the whole topic.
6. Repeat the complete explanation after study, and revisit on a later day.

This sequence is an application of the research, not a tested protocol. Keep the interface focused; do not require a full audio recording for every step or mistake a long sequence of tiny cards for understanding. Evaluate later unaided explanations and new scenarios alongside time and enjoyment. Separate read/viewed progress from demonstrated understanding and later retention.

Open decisions: frequency and form of checks, adaptation rules, hint design, content generation versus curated structure, and any gamification. No application code was changed for this research.
