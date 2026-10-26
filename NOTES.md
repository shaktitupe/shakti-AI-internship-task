# Notes

## How to run

1. Copy `cloud-flare.sh` to `cloud-flare.local.sh` and fill in your Cloudflare account ID and a Workers AI API token, keeping the double quotes. This file is in `.gitignore` and is never committed.
2. Run:

   ```
   python3 classify.py
   ```

   This sends each comment in `comments.json` to Clef, saves the raw answers to `results.json`, and writes the review page `results.html`. Open `results.html` in any browser.

Options:

- `python3 classify.py --model clef-flash` uses the faster, smaller model (the default is `clef`).
- `python3 classify.py --html-only` rebuilds `results.html` from `results.json` without calling Cloudflare again.

Only the Python standard library is used, so there is nothing to install.

## Tools and models

- **Classifier:** Cloudflare Workers AI, model `@cf/cloudflare/clef` (the larger Clef model), one question per comment, with the comment, author and thread as input.
- **Category definitions:** the instructions and the criteria for acceptable, toxic and spam are in `QUESTION` at the top of `classify.py`. Each criterion says what it covers and what it does not, so that blunt criticism of work or grading is not counted as toxic and genuine contributions are not counted as spam.
- **Review page:** colour-coded labels, Clef's probabilities and confidence, filters, search, a "least confident first" sort, and a way to flag mistakes and export them as Markdown.
- **AI assistance:** Claude (Opus 5.5) wrote `classify.py` and the category definitions, and guided me through GitHub Codespaces, Cloudflare and git.
- **My own work:** the review of Clef's labels in `MISTAKES.md`.

## How I found it

I am not a programmer and had barely used Git or GitHub before this, so most of the setup was new to me. I didn’t have Python installed, so I worked in GitHub Codespaces, which gave me a ready-made environment in the browser. Getting the Cloudflare account and API token, copying the repository and running commands in the terminal were all first-time steps for me.

I made a mistake early on: I typed a terminal command into .gitignore and put my token into cloud-flare.sh instead of cloud-flare.local.sh. I caught it with git status before anything was committed, and fixed it. That taught me more about how Git tracks files, and why secrets belong in a separate, ignored file, than reading about it would have.

I did not expect Clef to do as well as it did. I went through all 100 comments, and I agreed with every label it gave. The only problem I found was its confidence: it marked two clearly toxic comments as uncertain. The confidence scores turned out to be useful, because they point a reviewer to where the model is unsure, even when it is right.

It was a little hard to accept that a program could sort these comments as well as a person reading them carefully. Still, I don’t think it can be trusted on its own. A different set of comments, or subtler ones, could trip it up, so someone has to keep checking its work. Overall the task left me impressed with how far these tools have come, and with how much someone without a coding background can now build with AI’s help.
