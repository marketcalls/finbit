/**
 * The sources sheet: every publisher behind one story, and the line that says
 * the impact call is an AI assessment (CONTRACT.md section 10).
 *
 * A story on a FinBit card is a cluster, not an article: the pipeline merges
 * paraphrases of the same event and keeps the union of their sources. That makes
 * "Sources (5)" the single most important control on the card, because it is the
 * only way to get from a summarised, machine-scored claim back to the reporting
 * it came from. Everything here exists to make that trip short.
 *
 * Links open in the system browser through expo-linking rather than an in-app
 * web view: the publisher's own chrome, address bar and cookie state are part of
 * judging a source, and an embedded view hides all three. openURL can be
 * rejected (no handler for the scheme, or a malformed URL), so the failure is
 * caught and reported in the sheet instead of vanishing into a promise.
 *
 * The scrim is the dark page token at reduced opacity in both themes. A scrim
 * built from the active theme's own background would be a white wash over a
 * white sheet in light mode and read as a rendering fault.
 */

import * as Linking from 'expo-linking';
import { useCallback, useState, type ReactElement } from 'react';
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { relativeTime, sourceHost } from '@/src/lib/format';
import { type SourceRef } from '@/src/lib/types';
import { MIN_TOUCH_TARGET, darkColors, useTheme } from '@/src/theme';

/** How much of the screen the sheet may claim before it starts scrolling. */
const MAX_SHEET_HEIGHT = '82%';

const SCRIM_OPACITY = 0.6;

const GRABBER_WIDTH = 40;
const GRABBER_HEIGHT = 4;

/** CONTRACT.md section 10: this line belongs in the sources sheet, verbatim. */
const DISCLAIMER = 'AI assessment, not investment advice.';

function CloseGlyph({ color }: { color: string }): ReactElement {
  return (
    <Svg width={20} height={20} viewBox="0 0 24 24" fill="none">
      <Path d="M6 6L18 18M18 6L6 18" stroke={color} strokeWidth={2} strokeLinecap="round" />
    </Svg>
  );
}

function ExternalGlyph({ color }: { color: string }): ReactElement {
  return (
    <Svg width={16} height={16} viewBox="0 0 24 24" fill="none">
      <Path
        d="M14 4h6v6"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Path d="M20 4L10 14" stroke={color} strokeWidth={2} strokeLinecap="round" />
      <Path
        d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

export interface SourcesSheetProps {
  open: boolean;
  onClose: () => void;
  /** The story these sources belong to, shown so the sheet has context. */
  headline: string;
  sources: SourceRef[];
}

export function SourcesSheet({ open, onClose, headline, sources }: SourcesSheetProps): ReactElement {
  const { colors, radii, space, fonts, fontSizes, lineHeights } = useTheme();
  const insets = useSafeAreaInsets();
  const [linkError, setLinkError] = useState<string | null>(null);

  const openSource = useCallback(async (url: string) => {
    try {
      await Linking.openURL(url);
      setLinkError(null);
    } catch {
      // The URL itself is not shown back to the user: it is long, it wraps
      // badly, and the useful information is that nothing opened.
      setLinkError('That link could not be opened on this device.');
    }
  }, []);

  const sheet: ViewStyle = {
    backgroundColor: colors.card,
    borderTopLeftRadius: radii.lg,
    borderTopRightRadius: radii.lg,
    borderColor: colors.border,
    maxHeight: MAX_SHEET_HEIGHT,
    paddingBottom: insets.bottom + space.lg,
  };

  return (
    <Modal
      visible={open}
      transparent
      animationType="slide"
      statusBarTranslucent
      onRequestClose={onClose}
    >
      <View style={styles.root}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close the sources list"
          onPress={onClose}
          style={styles.scrimTarget}
        >
          <View style={[StyleSheet.absoluteFillObject, styles.scrim]} />
        </Pressable>

        <View accessibilityViewIsModal style={[styles.sheet, sheet]}>
          <View
            style={[
              styles.grabber,
              { backgroundColor: colors.border, borderRadius: radii.pill, marginTop: space.sm },
            ]}
          />

          <View style={[styles.header, { paddingHorizontal: space.lg, paddingTop: space.sm }]}>
            <View style={styles.headerText}>
              <Text
                accessibilityRole="header"
                style={{
                  color: colors.fg,
                  fontFamily: fonts.headline,
                  fontSize: fontSizes.xl,
                  lineHeight: lineHeights.xl,
                }}
              >
                Sources
              </Text>
              <Text
                numberOfLines={2}
                style={{
                  color: colors.mutedFg,
                  fontFamily: fonts.body,
                  fontSize: fontSizes.sm,
                  lineHeight: lineHeights.sm,
                  marginTop: space.xs,
                }}
              >
                {headline}
              </Text>
            </View>

            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close the sources list"
              onPress={onClose}
              hitSlop={space.sm}
              style={({ pressed }) => [
                styles.close,
                { borderRadius: radii.md, opacity: pressed ? 0.6 : 1 },
              ]}
            >
              <CloseGlyph color={colors.mutedFg} />
            </Pressable>
          </View>

          <ScrollView
            style={{ marginTop: space.md }}
            contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: space.md }}
          >
            {sources.length === 0 ? (
              <Text
                style={{
                  color: colors.mutedFg,
                  fontFamily: fonts.body,
                  fontSize: fontSizes.md,
                  lineHeight: lineHeights.md,
                  paddingVertical: space.lg,
                }}
              >
                No source links were recorded for this story.
              </Text>
            ) : (
              sources.map((source, index) => {
                const host = sourceHost(source.url);
                const when = relativeTime(source.published_at);

                return (
                  <Pressable
                    key={`${source.url}-${index}`}
                    accessibilityRole="link"
                    accessibilityLabel={`Open ${source.publisher} in the browser`}
                    accessibilityHint="Leaves FinBit and opens your browser"
                    onPress={() => void openSource(source.url)}
                    style={({ pressed }) => [
                      styles.source,
                      {
                        borderBottomColor: colors.border,
                        paddingVertical: space.md,
                        columnGap: space.md,
                        opacity: pressed ? 0.6 : 1,
                      },
                    ]}
                  >
                    <View style={styles.sourceText}>
                      <View style={[styles.sourceMeta, { columnGap: space.sm }]}>
                        <Text
                          numberOfLines={1}
                          style={{
                            color: colors.fg,
                            fontFamily: fonts.body,
                            fontSize: fontSizes.md,
                            fontWeight: '600',
                          }}
                        >
                          {source.publisher}
                        </Text>
                        {when === '' ? null : (
                          <Text
                            style={{
                              color: colors.mutedFg,
                              fontFamily: fonts.body,
                              fontSize: fontSizes.xs,
                            }}
                          >
                            {when}
                          </Text>
                        )}
                      </View>

                      {source.title ? (
                        <Text
                          numberOfLines={2}
                          style={{
                            color: colors.mutedFg,
                            fontFamily: fonts.body,
                            fontSize: fontSizes.sm,
                            lineHeight: lineHeights.sm,
                            marginTop: space.xs,
                          }}
                        >
                          {source.title}
                        </Text>
                      ) : null}

                      {host === '' ? null : (
                        <Text
                          numberOfLines={1}
                          style={{
                            color: colors.mutedFg,
                            fontFamily: fonts.mono,
                            fontSize: fontSizes.xs,
                            marginTop: space.xs,
                          }}
                        >
                          {host}
                        </Text>
                      )}
                    </View>

                    <View style={styles.sourceIcon}>
                      <ExternalGlyph color={colors.mutedFg} />
                    </View>
                  </Pressable>
                );
              })
            )}
          </ScrollView>

          {linkError === null ? null : (
            <Text
              accessibilityLiveRegion="polite"
              style={{
                color: colors.bear,
                fontFamily: fonts.body,
                fontSize: fontSizes.sm,
                paddingHorizontal: space.lg,
                paddingBottom: space.sm,
              }}
            >
              {linkError}
            </Text>
          )}

          <View
            style={{
              borderTopWidth: StyleSheet.hairlineWidth,
              borderTopColor: colors.border,
              paddingHorizontal: space.lg,
              paddingTop: space.md,
            }}
          >
            <Text
              style={{
                color: colors.mutedFg,
                fontFamily: fonts.body,
                fontSize: fontSizes.xs,
                lineHeight: lineHeights.xs,
              }}
            >
              {DISCLAIMER}
            </Text>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  scrimTarget: {
    ...StyleSheet.absoluteFillObject,
  },
  scrim: {
    backgroundColor: darkColors.bg,
    opacity: SCRIM_OPACITY,
  },
  sheet: {
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  grabber: {
    alignSelf: 'center',
    width: GRABBER_WIDTH,
    height: GRABBER_HEIGHT,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  headerText: {
    flex: 1,
    minWidth: 0,
  },
  close: {
    width: MIN_TOUCH_TARGET,
    height: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
  },
  source: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: MIN_TOUCH_TARGET,
  },
  sourceText: {
    flex: 1,
    minWidth: 0,
  },
  sourceMeta: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  sourceIcon: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
