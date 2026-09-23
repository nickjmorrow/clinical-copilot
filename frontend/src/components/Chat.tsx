import type { Ref } from 'react';
import Composer from 'src/components/Composer';
import MessageList from 'src/components/MessageList';
import useConversationStream from 'src/hooks/useConversationStream';

interface Props {
  /** Null while this is a draft — a conversation nobody has created yet. */
  conversationId: null | string;
  /** Handed to the composer, so the page can put text into it. */
  composerRef?: Ref<{ insert: (text: string) => void }>;
  /** Called once a draft's first message has given it an id. */
  onCreated: (id: string) => void;
}

/**
 * One conversation: a transcript and a box to type in.
 *
 * Everything that makes this app interesting — cursors, reattaching to a turn
 * already in flight, supersession, and creating the conversation on the first
 * message — is in `useConversationStream`. What is left here is the
 * arrangement, which is the whole reason the hook exists.
 *
 * A draft renders through this same component rather than a screen of its own.
 * The difference between "no messages yet" and "no conversation yet" is one
 * nullable id; a second component would be a second copy of the composer, and
 * the two would have drifted by the time anyone noticed.
 *
 * `ChatPage` mounts this with `key={conversationId ?? 'new'}`, so switching
 * conversations remounts rather than reusing this instance with new props.
 */
export default function Chat({ composerRef, conversationId, onCreated }: Props) {
  const { error, events, isStreaming, liveText, send, stop, thinkingText } = useConversationStream(
    conversationId,
    onCreated,
  );

  return (
    <div className={'flex min-h-0 flex-1 flex-col'}>
      <MessageList
        error={error}
        events={events}
        isStreaming={isStreaming}
        liveText={liveText}
        onAsk={send}
        thinkingText={thinkingText}
      />
      <Composer isStreaming={isStreaming} onSend={send} onStop={stop} ref={composerRef} />
    </div>
  );
}
