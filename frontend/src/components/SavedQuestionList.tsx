import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { listSavedQuestions, savedQuestionKeys } from 'src/api/savedQuestions';
import NewItemLink from 'src/components/NewItemLink';
import { describeQuestion } from 'src/format';
import { paths } from 'src/paths';

/**
 * The sidebar's list in Saved questions — name, and a one-line summary of
 * what it asks, so a list of ten does not read as ten identical rows until
 * you open each one.
 *
 * Fetches its own list rather than being handed one: `SavedQuestionsPanel`
 * beside it asks for the same query key, and TanStack answers both from one
 * request. Rows are links, so the page and the highlight here both follow
 * the address and cannot disagree about which question is open.
 */
export default function SavedQuestionList() {
  // `new`, an id, or null for nothing chosen — straight from the address.
  const { selection = null } = useParams();
  const questions = useQuery({ queryFn: listSavedQuestions, queryKey: savedQuestionKeys.all });

  return (
    <>
      <div className={'p-2'}>
        <NewItemLink
          isActive={selection === 'new'}
          label={'+ New question'}
          to={paths.saved('new')}
        />
      </div>

      {questions.error ? (
        <p className={'px-4 py-2 text-xs text-danger'}>Could not load your saved questions.</p>
      ) : (
        <ul className={'flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-2'}>
          {questions.data?.map((question) => (
            <li key={question.id}>
              <Link
                aria-current={question.id === selection ? 'page' : undefined}
                className={[
                  'flex w-full flex-col items-start gap-0.5 rounded-lg px-2.5 py-2 text-left transition',
                  question.id === selection
                    ? 'bg-accent/10 text-ink'
                    : 'text-ink-muted hover:bg-ink/5 hover:text-ink',
                ].join(' ')}
                to={paths.saved(question.id)}
              >
                <span className={'w-full truncate text-xs font-medium'}>{question.name}</span>
                <span className={'w-full truncate text-[11px] text-ink-muted'}>
                  {describeQuestion(question)}
                </span>
              </Link>
            </li>
          ))}
          {questions.data?.length === 0 && (
            <li className={'px-2.5 py-2 text-xs text-ink-muted'}>No saved questions yet.</li>
          )}
        </ul>
      )}
    </>
  );
}
