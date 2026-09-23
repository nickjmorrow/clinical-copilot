import type { ReactElement } from 'react';
import AssistantMessage from 'src/components/AssistantMessage';
import Bubble from 'src/components/Bubble';
import ToolCard from 'src/components/ToolCard';
import type { TurnItem } from 'src/turns';

interface Props {
  item: TurnItem;
}

/**
 * One `TurnItem`, dispatched to whatever draws it.
 *
 * Every item in the transcript goes through here, which is what keeps the
 * single render path honest: add a kind to `TurnItem` and TypeScript fails
 * here until it has somewhere to go. The return type is annotated rather than
 * inferred for exactly that reason — a switch that stops covering the union
 * falls out of the bottom returning `undefined`, which is a valid thing for a
 * component to do and therefore not an error unless the signature says so.
 *
 * The two message kinds are not symmetrical: an answer is markdown and gets
 * `AssistantMessage`, a typed message is literal text and gets a bare `Bubble`.
 * Rendering what somebody typed as markdown is a small betrayal — asterisks
 * they meant literally disappear into emphasis — and it buys nothing, because
 * the person who wrote it is the person reading it back.
 */
export default function TurnItemView({ item }: Props): ReactElement {
  switch (item.kind) {
    case 'assistant': {
      return <AssistantMessage text={item.text} />;
    }

    case 'tool': {
      return (
        <div className={'flex justify-start'}>
          <ToolCard
            data={item.data}
            durationMs={item.durationMs}
            input={item.input}
            isError={item.isError}
            name={item.name}
            result={item.result}
          />
        </div>
      );
    }

    case 'user': {
      return <Bubble role={'user'}>{item.text}</Bubble>;
    }
  }
}
