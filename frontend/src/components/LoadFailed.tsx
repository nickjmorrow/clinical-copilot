import { errorMessage } from 'src/api/client';
import Button from 'src/components/Button';
import EmptyState from 'src/components/EmptyState';

interface Props {
  error: unknown;
  onRetry: () => void;
  /** What could not be loaded, as a sentence: "Could not load the definitions." */
  title: string;
}

/**
 * A whole page whose data did not arrive: what failed, why, and a button to
 * try again — rather than a sentence with no way forward but a reload.
 */
export default function LoadFailed({ error, onRetry, title }: Props) {
  return (
    <EmptyState detail={errorMessage(error)} title={title}>
      <Button onClick={onRetry} variant={'primary'}>
        Try again
      </Button>
    </EmptyState>
  );
}
