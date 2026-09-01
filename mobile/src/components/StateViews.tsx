/**
 * The three states every list in this app owes the user: loading, nothing to
 * show, and something went wrong.
 *
 * CONTRACT_MOBILE_ADMIN.md section 8.1 requires all three on every list and
 * forbids rendering a raw error object, so these are written once here and the
 * feed, search, saved and article screens reuse them. An empty state that names
 * the active filter reads very differently from one that says "no news", which
 * is why the copy is a prop rather than baked in.
 *
 * Skeleton animates opacity only, and not at all when the phone asks for reduced
 * motion. A shimmer that ignores that setting is a genuine accessibility problem
 * for a full-screen pager where the placeholder fills the viewport.
 */

import { useEffect, useRef, useState, type ReactElement } from 'react';
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
  type DimensionValue,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

const PULSE_MS = 900;
const PULSE_MIN_OPACITY = 0.45;

/** Tracks the phone's reduce motion setting for the lifetime of the component. */
function useReduceMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (!cancelled) {
        setReduced(value);
      }
    });

    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', (value) => {
      setReduced(value);
    });

    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, []);

  return reduced;
}

export interface SkeletonProps {
  /** Defaults to filling the parent's width. */
  width?: DimensionValue;
  height?: number;
  /** Corner radius. Defaults to the small radius token. */
  radius?: number;
  style?: StyleProp<ViewStyle>;
}

/** One placeholder block. Compose several to sketch the shape of a real card. */
export function Skeleton({ width = '100%', height = 16, radius, style }: SkeletonProps): ReactElement {
  const { colors, radii } = useTheme();
  const reduceMotion = useReduceMotion();
  const pulse = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (reduceMotion) {
      pulse.setValue(1);
      return;
    }

    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: PULSE_MIN_OPACITY,
          duration: PULSE_MS,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 1,
          duration: PULSE_MS,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();

    return () => {
      loop.stop();
    };
  }, [pulse, reduceMotion]);

  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        {
          width,
          height,
          borderRadius: radius ?? radii.sm,
          backgroundColor: colors.muted,
          opacity: pulse,
        },
        style,
      ]}
    />
  );
}

export interface StateAction {
  label: string;
  onPress: () => void;
}

/** The shared button used by both states. Never smaller than the touch target. */
function ActionButton({ label, onPress }: StateAction): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [
        styles.action,
        {
          backgroundColor: colors.accent,
          borderRadius: radii.md,
          paddingHorizontal: space.xl,
          opacity: pressed ? 0.85 : 1,
        },
      ]}
    >
      <Text
        style={{
          color: colors.onAccent,
          fontFamily: fonts.body,
          fontSize: fontSizes.md,
          fontWeight: '600',
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export interface EmptyStateProps {
  title: string;
  /** One or two sentences that name the situation, not a generic apology. */
  body: string;
  action?: StateAction;
}

export function EmptyState({ title, body, action }: EmptyStateProps): ReactElement {
  const { colors, space, fonts, fontSizes, lineHeights } = useTheme();

  return (
    <View style={[styles.container, { padding: space.xl }]}>
      <Text
        accessibilityRole="header"
        style={{
          color: colors.fg,
          fontFamily: fonts.headline,
          fontSize: fontSizes.xl,
          lineHeight: lineHeights.xl,
          textAlign: 'center',
        }}
      >
        {title}
      </Text>
      <Text
        style={{
          color: colors.mutedFg,
          fontFamily: fonts.body,
          fontSize: fontSizes.md,
          lineHeight: lineHeights.md,
          marginTop: space.sm,
          textAlign: 'center',
        }}
      >
        {body}
      </Text>
      {action ? (
        <View style={{ marginTop: space.xl }}>
          <ActionButton {...action} />
        </View>
      ) : null}
    </View>
  );
}

export interface ErrorStateProps {
  /** A sentence, from describeError(). Never an exception object. */
  message: string;
  onRetry: () => void;
  /** Defaults to a neutral heading; override it when the cause is known. */
  title?: string;
  retryLabel?: string;
}

export function ErrorState({
  message,
  onRetry,
  title = 'Something went wrong',
  retryLabel = 'Try again',
}: ErrorStateProps): ReactElement {
  const { colors, space, fonts, fontSizes, lineHeights } = useTheme();

  return (
    <View
      accessibilityLiveRegion="polite"
      style={[styles.container, { padding: space.xl }]}
    >
      <Text
        accessibilityRole="header"
        style={{
          color: colors.fg,
          fontFamily: fonts.headline,
          fontSize: fontSizes.xl,
          lineHeight: lineHeights.xl,
          textAlign: 'center',
        }}
      >
        {title}
      </Text>
      <Text
        style={{
          color: colors.mutedFg,
          fontFamily: fonts.body,
          fontSize: fontSizes.md,
          lineHeight: lineHeights.md,
          marginTop: space.sm,
          textAlign: 'center',
        }}
      >
        {message}
      </Text>
      <View style={{ marginTop: space.xl }}>
        <ActionButton label={retryLabel} onPress={onRetry} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  action: {
    minHeight: MIN_TOUCH_TARGET,
    minWidth: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
