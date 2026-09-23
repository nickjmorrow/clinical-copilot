import { useQuery } from '@tanstack/react-query';
import { listSavedQuestions, savedQuestionKeys } from 'src/api/savedQuestions';
import DashboardCard from 'src/components/DashboardCard';
import EmptyState from 'src/components/EmptyState';

/**
 * Every saved question, run and shown together — SEMANTIC_LAYER.md § 17: "a
 * set of saved questions on one page". Deliberately just that: no picking
 * which questions belong, no layout to arrange, no separate "dashboard"
 * entity to create and maintain. A saved question already is the unit this
 * project trusts to re-ask itself correctly; a dashboard is what showing all
 * of them at once looks like, not a second thing to build.
 */
export default function Dashboard() {
  const questions = useQuery({ queryFn: listSavedQuestions, queryKey: savedQuestionKeys.all });

  if (questions.error) return <EmptyState title={'Could not load your saved questions.'} />;

  if (questions.data?.length === 0) {
    return (
      <EmptyState
        detail={
          'Save one under Saved questions and it shows up here, run fresh every time you open this page.'
        }
        title={'No saved questions yet.'}
      />
    );
  }

  return (
    <div className={'h-full overflow-y-auto px-6 py-5'}>
      <div className={'mx-auto flex max-w-4xl flex-col gap-4'}>
        <div>
          <h2 className={'text-sm font-semibold tracking-tight text-ink'}>Dashboard</h2>
          <p className={'mt-1 text-xs text-ink-muted'}>
            Every saved question, run fresh each time this page opens.
          </p>
        </div>
        {questions.data?.map((question) => (
          <DashboardCard key={question.id} question={question} />
        ))}
      </div>
    </div>
  );
}
