/**
 * The placeholder shown while the first page of the feed is in flight.
 *
 * It is deliberately the shape of a real card rather than a spinner: on a
 * full-screen pager the loading view fills the entire viewport, and a centred
 * spinner in that much space reads as a stalled app. A card-shaped placeholder
 * tells the user what is coming and, because it occupies the same boxes, the
 * real card lands without the layout jumping.
 *
 * The pulse, and its suspension under reduce motion, belong to Skeleton in
 * StateViews. Nothing animates here.
 */

import { type ReactElement } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';

import { Skeleton } from '@/src/components/StateViews';
import { useTheme } from '@/src/theme';

/** Matches the banner ratio and the cap that CardImage uses on a full card. */
const BANNER_ASPECT = 16 / 9;
const BANNER_MAX_FRACTION = 0.34;

const THUMB_SIZE = 72;

/** Line heights of the blocks that stand in for the headline and the summary. */
const HEADLINE_LINE = 26;
const BODY_LINE = 13;

export interface FeedSkeletonProps {
  /**
   * The pager viewport height. The placeholder fills it exactly so the skeleton
   * and the card that replaces it occupy the same page.
   */
  height?: number;
  /** A compact leading-thumbnail row, for a search or saved list. */
  compact?: boolean;
}

export function FeedSkeleton({ height, compact = false }: FeedSkeletonProps): ReactElement {
  const { colors, radii, space } = useTheme();
  const { width } = useWindowDimensions();

  if (compact) {
    return (
      <View
        style={[
          styles.compact,
          {
            backgroundColor: colors.card,
            borderColor: colors.border,
            borderRadius: radii.md,
            padding: space.lg,
            columnGap: space.md,
          },
        ]}
      >
        <Skeleton width={THUMB_SIZE} height={THUMB_SIZE} radius={radii.md} />
        <View style={[styles.grow, { rowGap: space.sm }]}>
          <Skeleton height={HEADLINE_LINE} width="90%" />
          <Skeleton height={BODY_LINE} />
          <Skeleton height={BODY_LINE} width="70%" />
        </View>
      </View>
    );
  }

  const banner = Math.round(
    Math.min(
      (width - 2 * space.lg) / BANNER_ASPECT,
      (height ?? Number.POSITIVE_INFINITY) * BANNER_MAX_FRACTION,
    ),
  );

  return (
    <View
      accessibilityLabel="Loading stories"
      accessibilityRole="progressbar"
      style={[
        styles.page,
        {
          height,
          backgroundColor: colors.bg,
          paddingHorizontal: space.lg,
          paddingTop: space.lg,
          paddingBottom: space.xl,
          rowGap: space.lg,
        },
      ]}
    >
      <Skeleton height={banner} radius={radii.lg} />

      <View style={{ rowGap: space.sm }}>
        <Skeleton height={BODY_LINE} width="40%" />
        <Skeleton height={HEADLINE_LINE} />
        <Skeleton height={HEADLINE_LINE} width="80%" />
      </View>

      <View style={{ rowGap: space.sm }}>
        <Skeleton height={BODY_LINE} />
        <Skeleton height={BODY_LINE} />
        <Skeleton height={BODY_LINE} width="85%" />
      </View>

      <View style={[styles.row, { columnGap: space.sm }]}>
        <Skeleton width={120} height={30} radius={radii.pill} />
        <Skeleton width={92} height={30} radius={radii.pill} />
      </View>

      <View style={[styles.row, styles.footer, { columnGap: space.sm }]}>
        <Skeleton width={96} height={20} />
        <View style={styles.grow} />
        <Skeleton width={28} height={28} radius={radii.sm} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: {
    width: '100%',
  },
  compact: {
    flexDirection: 'row',
    borderWidth: StyleSheet.hairlineWidth,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  footer: {
    marginTop: 'auto',
  },
  grow: {
    flex: 1,
  },
});
