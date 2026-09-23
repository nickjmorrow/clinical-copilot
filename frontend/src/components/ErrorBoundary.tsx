import { Component, type ErrorInfo, type ReactNode } from 'react';
import Button from 'src/components/Button';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * The last line of defence.
 *
 * Without one of these, a single render throwing anywhere in the tree unmounts
 * the whole app and leaves a blank white page — no message, no reload button,
 * nothing in the UI to tell you it even happened. That is the worst failure
 * mode an app has, and it costs twenty lines to replace with a sentence.
 *
 * Still a class component, and not because nobody got round to it: this is the
 * one thing React has no hook for. `componentDidCatch` has no function
 * equivalent.
 */
export default class ErrorBoundary extends Component<Props, State> {
  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  state: State = { error: null };

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Where an error tracker goes. Until there is one, the console is the only
    // record that exists — a white page tells you nothing, and this at least
    // leaves the stack somewhere a developer will look.
    console.error('Unhandled render error', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className={'flex h-full flex-col items-center justify-center gap-3 p-8 text-center'}>
        <p className={'text-sm font-medium text-ink'}>Something broke.</p>
        <p className={'max-w-md text-xs text-ink-muted'}>{this.state.error.message}</p>
        <Button onClick={() => window.location.reload()} variant={'primary'}>
          Reload
        </Button>
      </div>
    );
  }
}
