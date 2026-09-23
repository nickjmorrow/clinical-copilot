interface Props {
  onAsk: (question: string) => void;
}

/**
 * The questions offered on an empty conversation: one of each shape the app
 * answers — a list of patients, an aggregate broken down (which draws a
 * chart), and a question about the data itself.
 *
 * What this app can answer is exactly the set of terms in
 * `clinical_definitions`, and that set is not guessable from a blank text box.
 * This list used to open with "What can I ask you about?" for that reason —
 * a model turn spent reciting the vocabulary. "What can I ask?" in the header
 * now shows the same vocabulary instantly, from the live table, and each term
 * in it drops into the box below; so the slot goes to showing a second kind of
 * answer instead.
 *
 * The questions name defined terms in plain words rather than listing terms
 * here: a hard-coded list would be a second copy of the vocabulary, wrong the
 * first time a definition changed.
 */
export default function StarterQuestions({ onAsk }: Props) {
  const questions = [
    'What patients are on a nephrotoxic medication and have impaired kidney function?',
    "What's the average eGFR for patients with impaired kidney function, by age band?",
    'What is in this dataset?',
  ];

  return (
    <div className={'mt-5 flex flex-col items-stretch gap-2'}>
      {questions.map((question) => (
        <button
          className={
            'rounded-lg border border-ink/10 bg-surface-raised px-3 py-2 text-left text-xs text-ink-muted transition hover:border-ink/20 hover:text-ink'
          }
          key={question}
          onClick={() => {
            onAsk(question);
          }}
          type={'button'}
        >
          {question}
        </button>
      ))}
    </div>
  );
}
