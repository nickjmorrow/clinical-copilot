import EmptyState from 'src/components/EmptyState';

/**
 * What a page behind the curator or auditor role shows everyone else: why it
 * is closed, instead of an error that reads as the app being broken — and
 * where the open half is, since the definitions themselves are readable by
 * anyone. On a public deployment every visitor holds no roles.
 */
export default function CuratorsOnly() {
  return (
    <EmptyState
      detail={
        'This part of the app is limited to curators and auditors. The definitions every answer relies on are open to everyone, under Definitions.'
      }
      title={'For curators and auditors'}
    />
  );
}
