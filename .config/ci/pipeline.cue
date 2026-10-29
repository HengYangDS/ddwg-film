package ci

// The installed verification is the whole pipeline: hosted CI runs the portable full proof on
// Apple-silicon macOS. The film gates need the supplied models, a rebuild and the published
// release, so they run only locally.
