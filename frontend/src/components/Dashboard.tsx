import { useQuery } from '@tanstack/react-query';
import { listSavedQuestions, savedQuestionKeys } from 'src/api/savedQuestions';
import DashboardCard from 'src/components/DashboardCard';
import EmptyState from 'src/components/EmptyState';
import LoadFailed from 'src/components/LoadFailed';
import Loading from 'src/components/Loading';
import Page from 'src/components/Page';

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

  if (questions.error) {
    return (
      <LoadFailed
        error={questions.error}
        onRetry={() => void questions.refetch()}
        title={'Could not load your saved questions.'}
      />
    );
  }

  if (questions.isPending) return <Loading />;

  if (questions.data.length === 0) {
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
    <Page
      description={'Every saved question, run fresh each time this page opens.'}
      title={'Dashboard'}
      width={'table'}
    >
      {questions.data.map((question) => (
        <DashboardCard key={question.id} question={question} />
      ))}
    </Page>
  );
}
