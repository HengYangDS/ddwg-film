# film-production Specification

## Purpose

Make the department-wide DDWG work principles and their relationships understandable
through source-grounded Chinese and English films, with verified media, explicit review limits
and reproducible governed delivery.

## Requirements

### Requirement: Faithful Complete DDWG Film

The production SHALL explain the current canonical charter and all six topics
as an intelligible department-wide work-quality contract. It SHALL preserve
source distinctions, naturally explain terms before relying on them, and use
bounded illustrative examples without implying deployment or adoption.

#### Scenario: Viewer understands the relationship among topics

- **WHEN** a viewer follows the opening, six topics and closing
- **THEN** evidence, judgment, authority, delivery and improvement form a coherent argument
- **AND** no mandatory sequential pipeline or narrow business scope is implied

#### Scenario: Viewer follows the complete narrative

- **WHEN** a viewer watches either delivered language edition
- **THEN** judgment, data, delivery, human-Agent collaboration, communication
  and practice evolution are intelligible without undefined specialist terms
- **AND** the ending returns naturally to the opening and DDWG's purpose

#### Scenario: Each sentence is faithful, clear on first hearing and idiomatic

- **WHEN** an independent language review reads every thought and label of both
  editions against its source passage
- **THEN** fidelity, first-hearing clarity and idiom each score at least 90, with no
  material finding
- **AND** compressed formulas and calques are replaced or explained in plain words,
  so a rule is heard as what people do rather than as an abstract formula
- **AND** each source term keeps its exact counterpart in the words a quantitative
  hedge fund's data department uses, explained once where needed and never replaced
  by a nearby everyday word
- **AND** each idea keeps one word across the edition

#### Scenario: A first-time viewer keeps each point

- **WHEN** independent listeners from different parts of the department, outside
  the topic's specialty, hear each thought of an edition once and in order
- **THEN** no thought loses its point, and every part that changes who decides,
  what is allowed or what counts as done is still heard
- **AND** a lost point, one idea heard under different words, or a source term
  rendered by a word that changes its meaning or register is a material finding of
  the final review

### Requirement: Exact Native Media And Connected Performance

The production SHALL produce independently understandable Chinese and English
editions, each exactly 1500 seconds at native progressive 60 fps with a UHD
master and a captioned 1080p viewing edition, the selected narrator, 48 kHz
stereo narration only, no music and purposeful orderly 2D motion. It SHALL
qualify actual changed media and all transitions before it replaces the viewing
edition, and each film SHALL carry the release metadata its script declares.

#### Scenario: Revised edition preserves the release contract

- **WHEN** the revised edition is delivered
- **THEN** the exact media counts, safe geometry and audiovisual timing are checked
- **AND** observed review modalities and unobserved listening remain separately stated

#### Scenario: Complete deliverable is qualified

- **WHEN** the release is packaged
- **THEN** whole-file decoding, exact counts, synchronized caption bounds,
  moving geometry, source bindings and current delivery hashes are verified
- **AND** small single-line captions, a designed cover, author metadata, a
  transcript, chapters, a usable player and source and license bindings exist
- **AND** each film reads back the release metadata its script declares
- **AND** model review and unobserved human listening remain separately stated

#### Scenario: Release metadata reads back

- **WHEN** a film is packaged
- **THEN** its title, author, collection, genre, year, description, comment,
  synopsis, keywords and copyright read back from the film as its script declares them
- **AND** its picture and narration tracks carry their names and the edition's language

### Requirement: Narration keeps the voice and its phrase endings

The narrator SHALL synthesize every authored thought group through the official
model and vendor generator, conditioned on the approved reference recording,
with fixed sampling settings, deterministic seeds, non-streaming decoding, no
pitch or tempo change and any in-context repetition penalty its cast declares.
Each selected take SHALL end on its own and SHALL read each word whose reading
depends on its context as that context requires.

#### Scenario: A declared penalty restores natural Chinese endings

- **WHEN** the Chinese cast declares a penalty in [1, 1.5) with an in-context reference
- **THEN** each thought group is generated with that penalty and the record retains it
- **AND** a value outside that range, or one without an in-context reference, refuses before synthesis

#### Scenario: A clear reference keeps the narrator's identity

- **WHEN** a cast speaks from an in-context reference derived from the approved identity root
- **THEN** the cast records the root's hashes and every derivation step with its mode, text, seed and settings
- **AND** the reference's voiced audio is native model output with only its edges and inner silences shortened
- **AND** the recorded comparison shows the root's speaker identity and pitch kept with clearer voicing

#### Scenario: Each take ends on its own

- **WHEN** a thought take is selected
- **THEN** its last syllable is complete and dies away inside the take, as the
  take's own ending measurement shows
- **AND** no take is selected whose ending the assembly would have to release
  with a fade

#### Scenario: Each polyphone is read in context

- **WHEN** a selected take speaks a word whose reading depends on its context
- **THEN** the reading measured on the recording, by its phones or by the pitch
  contour of its syllable, is the reading its context requires
- **AND** a misreading the model keeps is resolved by a retake or by an exact
  equivalent without the polyphone, never by a word that changes the meaning

### Requirement: Thought retakes bind their exact text

A thought-level retake SHALL bind its seed to the exact text of the thought it
replaces. Reuse of a recorded thought SHALL require the same text, seed and
settings.

#### Scenario: A thought retake replaces only its own thought

- **WHEN** a retake names a thought index, a seed and the hash of that thought's text
- **THEN** only that thought is regenerated with the declared seed
- **AND** a stale text hash, an unknown index or a seed equal to the base seed refuses
- **AND** reuse of a cached thought requires the same text, seed and settings

### Requirement: Designed pauses preserve speech and runtime

The assembly SHALL keep every recorded speech sample. It SHALL set distinct
thought, question, paragraph, chapter, opening and closing pauses from the
script's declared pause policy, moving only measured quiet within a thought. The
native quiet beside each inserted designed quiet SHALL fade into and out of it.
It SHALL allocate the remaining runtime by declared weights within declared
limits and preserve complete phrase tails. Each soundtrack SHALL be exact
1500-second, 48 kHz stereo.

#### Scenario: Pauses fit the exact runtime

- **WHEN** the designed pauses and recorded speech are assembled
- **THEN** opening, paragraph and chapter gaps absorb the remaining runtime within their limits
- **AND** speech is neither accelerated nor padded with long silence
- **AND** no inserted designed quiet begins or ends on a step in the native quiet
- **AND** an incomplete pause policy or insufficient runtime refuses before output

### Requirement: Long pauses inside a thought are capped

When the script declares an inner pause cap, a native pause inside a thought
that is longer than the cap SHALL be shortened to it by removing quiet from its
middle through a short crossfade, before thought boundaries are measured.

#### Scenario: A long pause inside a thought is capped

- **WHEN** the script declares an inner pause cap
- **THEN** every native pause inside a thought that is longer than the cap is shortened to the cap
- **AND** shorter pauses, speech samples and thought joins are unchanged
- **AND** a cap below 0.2 seconds or above the thought pause refuses before output

### Requirement: Punctuation inside a thought is heard as graded breaks

When the script declares inner pause floors, each native pause inside a thought
SHALL last at least the largest floor declared for the marks written between
its two aligned words, so a sentence end is heard as a longer break than a
clause mark and a clause mark as a longer one than a comma. The added quiet
SHALL be digital zero in the middle of the heard quiet, with fades of the native
quiet beside it, and SHALL leave speech samples and thought joins unchanged.

#### Scenario: A sentence end inside a thought outlasts a comma

- **WHEN** the script declares inner pause floors
- **THEN** every native pause inside a thought lasts at least the floor of its marks, and aligned word times move with the added quiet
- **AND** a pause spoken without native quiet, speech samples and thought joins are unchanged
- **AND** every lengthened pause is recorded with the assembly
- **AND** overlapping marks, or a floor below 0.05 seconds or above the inner cap, refuses before output

### Requirement: Long runs of speech take a breath

When the script declares a breath group with its inner pause floors, a run of
speech longer than the group between pauses of at least the breath pause SHALL
take that pause at the floored mark nearest its middle, until every run fits or
has no such mark left.

#### Scenario: A long run breathes at the mark nearest its middle

- **WHEN** the script declares a breath group
- **THEN** a run of speech longer than the group takes the breath pause at the floored mark nearest its middle
- **AND** a run that fits, or that has no floored mark left, keeps its pauses
- **AND** a breath group without floors, a group outside 3 to 20 seconds, or a pause below 0.1 seconds or above the inner cap refuses before output

### Requirement: Statement pauses follow the thought

A statement pause SHALL grow with the spoken length of the thought it follows,
within the script's declared range, while the edition's mean statement pause
stays the declared thought pause. A question SHALL keep the question pause.
When the script declares a coda thought pause, every thought boundary of the
closing segment SHALL last at least that pause.

#### Scenario: A longer thought settles longer

- **WHEN** statement pauses are designed for an edition
- **THEN** a longer thought is followed by a longer pause within the declared range
- **AND** the mean statement pause equals the declared thought pause, so the runtime allocation is unchanged
- **AND** a question keeps the question pause

#### Scenario: The coda settles on its own pause

- **WHEN** the script declares a coda thought pause
- **THEN** every thought boundary of the closing segment lasts at least that pause
- **AND** a coda pause shorter than the thought pause or longer than 2 seconds refuses before output

### Requirement: Thought boundaries are the stronger break

Quiet SHALL be measured as heard: 10 ms frames whose channel-mean RMS is at most
-55 dBFS before the program gain. Every thought boundary SHALL be heard at least
the declared boundary ratio times the longest heard quiet inside the thoughts on
either side of it. A recording that meets digital silence while still heard
SHALL be released over its last 60 ms.

#### Scenario: A boundary outlasts the quiet beside it

- **WHEN** thought pauses are designed for an edition
- **THEN** every thought boundary is heard longer than the longest quiet inside either neighbouring thought by the declared ratio
- **AND** a boundary that the declared mean cannot fund refuses before output

#### Scenario: A recording still heard at digital silence is released

- **WHEN** a thought recording meets digital silence in a join, or a segment's voice ends, while its last 10 ms are heard
- **THEN** its last 60 ms fade to silence through a raised cosine and the released samples are recorded with the assembly
- **AND** a recording already below heard quiet keeps its 10 ms soft edge and every earlier sample is unchanged

### Requirement: Thought levels follow their segment

Before pauses are designed, a thought whose BS.1770 loudness over its aligned
speech differs from the median loudness of its segment's thoughts by more than
the declared tolerance SHALL be brought within it by one static gain of at most
3 dB that changes in the quiet between thoughts. Speech timing and the dynamics
within a thought SHALL stay unchanged.

#### Scenario: A loud or soft thought is leveled

- **WHEN** a segment's thoughts are leveled
- **THEN** each thought's loudness lies within the tolerance of the segment median, or its gain is at the 3 dB bound
- **AND** every gain and level is recorded with the assembly

### Requirement: Paragraph pauses follow the paragraph

A paragraph gap SHALL grow with the spoken length of the paragraph it follows,
within the script's declared range, while the edition's mean paragraph gap
before allocation stays the declared paragraph pause. Opening and chapter gaps
SHALL keep their declared pauses.

#### Scenario: A longer paragraph settles longer

- **WHEN** the gap before each segment is designed for an edition
- **THEN** a longer paragraph is followed by a longer gap within the declared range
- **AND** the mean paragraph gap equals the declared paragraph pause before the remaining runtime is allocated
- **AND** opening and chapter gaps keep their declared pauses

### Requirement: Both editions play at one program level

Each assembled soundtrack SHALL reach one declared spoken-word program level
through a single linear gain, without dynamics processing and at or below a
declared true-peak ceiling.

#### Scenario: One gain reaches the declared level

- **WHEN** a soundtrack has been assembled
- **THEN** one gain brings its integrated loudness within 0.5 LU of the declared level with true peak at or below the ceiling
- **AND** the measured level before and after the gain is recorded and checked by the film gate

### Requirement: Independently understandable bilingual narrative

The two editions SHALL preserve the same verified source meaning, complete topic
coverage and selected narrator identity. Each SHALL define the central problem
before explaining its answers, introduce terms before relying on them, unfold
through a natural connected argument and return the coda to the opening.
English SHALL use idiomatic connected exposition, with pronunciation and stress
qualified from its actual recording rather than inferred from written text.

#### Scenario: Both language editions are delivered

- **WHEN** the release is qualified and delivered
- **THEN** Chinese and English each satisfy the full 1500-second release contract
- **AND** current recordings, captions, picture, reviews and destination hashes
  are independently bound to each language
- **AND** source-text review does not substitute for actual audio or motion review

### Requirement: A representative sample precedes the whole-film render

A whole-film render SHALL follow an encoded representative sample of 60 to 120
seconds in both languages. The sample SHALL cover the same content in both
languages and show the changed narration and picture.

#### Scenario: A sample demonstrates the revision

- **WHEN** a revision changes the narration or the picture treatment
- **THEN** both languages' samples are rendered from the current inputs and reviewed
- **AND** sample review establishes no whole-film acceptance

### Requirement: The final film earns an evidence-bound composite review

The final film MUST meet the review contract the repository declares. The
review MUST bind the actual final media and distinguish observed modalities
from unassessed ones. Technical qualification MUST NOT imply human taste. Audio
dimensions MUST be scored from automated evidence; human listening is a later
acceptance after delivery, not a scoring criterion.

#### Scenario: Final composite review qualifies

- **WHEN** all eight review dimensions have been assessed against the final files
- **THEN** every dimension is at least 90
- **AND** the overall score, the mean of the dimensions, is therefore at least 90
- **AND** every audio deduction cites a measured or observed property, never the absence of human listening
- **AND** no material semantic, pronunciation, readability, continuity or delivery finding remains

#### Scenario: The verifier enforces the recorded review

- **WHEN** the film-media gate verifies final acceptance for an edition
- **THEN** the review record must name both published movie hashes, the current script and composition
- **AND** a rebuilt movie inherits that review only by meeting the reproduction standard against its published movie
- **AND** missing dimensions, a mismatched mean, a score below threshold or a material finding refuses
- **AND** human listening is reported as recorded, never inferred from model review or measurements

### Requirement: Bounded Local Narration Memory

Local narration SHALL cap the speech model's retained GPU buffer cache at
2 GiB for the whole synthesis process, so buffers that a segment frees above
the cap return to the system during generation instead of accumulating until
the segment ends. The cap SHALL NOT change synthesized audio.

#### Scenario: Segment generation frees more than the cap

- **WHEN** a narration segment frees more than 2 GiB of GPU buffers while it
  is generated
- **THEN** the retained buffer cache stays within 2 GiB after each new
  allocation
- **AND** the written waveform bytes equal those produced without the cap for
  the same inputs and seed

### Requirement: Composition supports the audience throughout motion on a fixed canvas

The film MUST use consistent anchors, optical alignment, deliberate spacing
between objects and labels, controlled reading groups and content-appropriate
density. Its layout MUST vary with the argument rather than repeat a
title-and-panel master. Every scene MUST show its subject from its first spoken
words.

#### Scenario: The audience follows a changing relationship

- **WHEN** records move, a comparison unfolds or a connected scene changes
- **THEN** essential identities, conditions and the reading focus remain understandable
- **AND** captions and labels remain separated and readable at the viewing size
- **AND** neither static geometry nor blank space substitutes for comprehension

#### Scenario: Speech never plays over an empty picture

- **WHEN** any segment's narration is playing
- **THEN** its scene paints visible content in every half-second interval
- **AND** no checked frame during speech, or in a pause within a chapter, dims below 30 levels above the ground
- **AND** no half second of speech keeps the scene's brightest mark below 90 levels above the ground
- **AND** each chapter's first scene stands at half its steady contrast on the chapter's first word
- **AND** the real-browser geometry check finds no overlap, safe-area overflow
  or label collision in the actual staged film

#### Scenario: A name appears in its place on its words

- **WHEN** a stage holds a place that a later word will name
- **THEN** nothing marks that place before its words: no dashed line, ring, slot or frame stands in for the name
- **AND** the name and its mark appear together in their place on those words, while the structure they belong to stays drawn solid
- **AND** words that name a group, such as a count, a collective noun or a span, may draw the group's own outlines solid on those words, and each member then takes its name on its own words
- **AND** a dashed stroke appears only where it shows an unknown, hypothetical or missing thing that the narration names

#### Scenario: A transition leaves no ghost, residue or stall

- **WHEN** one layer of a scene gives way to another in the same place
- **THEN** the outgoing and incoming layers share the mid-ink band for at most four frames at 30 fps
- **AND** an outline or seat stays under the mark that fills it instead of cross-fading into it
- **AND** no mark rests below legible ink for more than 0.7 s, and no 3.5 s of speech holds the picture still

#### Scenario: A scene or stage changes on the words that name it

- **WHEN** a scene within a chapter, or a stage within a scene, gives way to the next
- **THEN** the incoming picture arrives on the words that name its first mark, and the outgoing picture holds until then
- **AND** the incoming picture replaces the outgoing one in a single frame, so the two never stand together and the frame never passes through bare ground
- **AND** the structure a thought names stands from its first words, so no thought's legible marks span under 5% of the picture 2 s into it
- **AND** no join between two thoughts of a chapter changes more than half of its legible marks in the quiet between them

#### Scenario: A stage is drawn at the size it is composed for

- **WHEN** a stage is drawn
- **THEN** it keeps the size and place its layout gives it, so the picture never zooms, pans or rescales between thoughts
- **AND** a sparse stage is composed larger on the canvas instead of being drawn through a closer frame

#### Scenario: A label appears with the words that name it

- **WHEN** a label, or one part of a growing label, quotes words its scene speaks
- **THEN** it becomes legible no more than 0.3 s before the clause that speaks it begins
  and no more than 1.5 s ahead of its words within that clause
- **AND** it becomes legible no later than 0.5 s after those words end
