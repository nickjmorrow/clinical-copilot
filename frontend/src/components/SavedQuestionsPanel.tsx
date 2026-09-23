import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { listSavedQuestions, savedQuestionKeys } from 'src/api/savedQuestions';
import EmptyState from 'src/components/EmptyState';
import SavedQuestionDetail from 'src/components/SavedQuestionDetail';
import SavedQuestionForm from 'src/components/SavedQuestionForm';
import { paths } from 'src/paths';

/**
 * Saved questions — SEMANTIC_LAYER.md § 17: a named cohort you can pin and
 * re-run. The list is in the sidebar (`SavedQuestionList`); this is the page
 * beside it — the create form, one question, or a prompt to pick one.
 *
 * An id in the address is attempted, not trusted: until the list has loaded
 * there is nothing to show, and an id it does not contain gets a sentence
 * rather than a blank page. That matters now that a question has a URL
 * somebody might bookmark and then delete the question behind.
 */
export default function SavedQuestionsPanel() {
  // `new`, an id, or null for nothing chosen — straight from the address.
  const { selection = null } = useParams();
  const navigate = useNavigate();
  const questions = useQuery({ queryFn: listSavedQuestions, queryKey: savedQuestionKeys.all });

  if (selection === null) {
    return (
      <EmptyState
        detail={
          'Running one re-asks the definitions layer every time — an edited threshold changes the answer, the way it would if you asked in chat.'
        }
        title={'Pick a saved question to run, or save a new one.'}
      />
    );
  }

  if (selection === 'new') {
    return (
      <SavedQuestionForm
        onCreated={(id) => {
          // The form became this question; Back should not reopen it empty.
          void navigate(paths.saved(id), { replace: true });
        }}
      />
    );
  }

  if (questions.isPending) return null;
  if (questions.error) return <EmptyState title={'Could not load your saved questions.'} />;

  const question = questions.data.find((one) => one.id === selection);
  if (!question) {
    return (
      <EmptyState
        detail={'It may have been deleted. Pick another from the list.'}
        title={'That saved question is not available.'}
      />
    );
  }

  return (
    <SavedQuestionDetail
      key={question.id}
      onDeleted={() => {
        void navigate(paths.saved());
      }}
      question={question}
    />
  );
}
