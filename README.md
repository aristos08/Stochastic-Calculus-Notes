# Stochastic Calculus Notes

Lecture notes for ACTSC 969 (Stochastic Calculus), University of Waterloo, published as a static website.

## Layout

- `src/` holds the LaTeX sources, one file per chapter (`01-martingales.tex`, ...).
- `src/preamble.tex` holds the math macros (`\mcal`, `\Prob`, `\E`, ...). They are passed to MathJax.
- `src/figures/` holds SVG versions of the TikZ figures. Browsers can't run TikZ, so each `figure` environment carries a `%html-figure: name.svg` comment that points at its SVG.
- `assets/style.css` is the stylesheet.
- `docs/` is the generated site, served by GitHub Pages. Don't edit it by hand.

## Building

```
python3 build.py
```

This needs only Python 3, with no other dependencies. Equations are rendered in the browser by [MathJax](https://www.mathjax.org/).

## Adding a chapter

1. Add `src/NN-name.tex`, starting with `\chapter{...}` and using `\section{Lecture N}` for each lecture.
2. Add `("name", "NN-name.tex")` to `CHAPTERS` in `build.py`.
3. Add any new macros to `src/preamble.tex`.
4. Run `python3 build.py`, and fix anything it prints as a warning.
