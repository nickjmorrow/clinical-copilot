import EmptyState from 'src/components/EmptyState';

/**
 * What a page behind the curator or auditor role shows everyone else: why it
 * is closed, instead of an error that reads as the app being broken. On a
 * public deployment every visitor sees this, because visitors hold no roles.
 */
export default function CuratorsOnly() {
  return (
    <EmptyState
      detail={
        'This part of the app reviews and edits the definitions every answer relies on, so it is limited to curators and auditors. "What can I ask?" in Chat shows every definition and the reasoning behind it.'
      }
      title={'For curators and auditors'}
    />
  );
}
