/**
 * The anonymous device handshake, run once behind the splash.
 *
 * There is no login in FinBit and there never will be one
 * (CONTRACT_MOBILE_ADMIN.md section 8.1). On first launch the app registers
 * itself, receives a device id, a device secret and a token pair, and stores the
 * first three in SecureStore. Every later launch reuses them. The user is never
 * asked for anything.
 *
 * Children render only once that has succeeded, because every screen below this
 * assumes a signed request will work. A failure shows a retry screen, never a
 * sign-in form: the handshake failing means the phone is offline or the API is
 * down, and asking someone to log in to an app with no accounts would be a lie
 * about what went wrong.
 *
 * The client itself single-flights registration and refreshes tokens on demand,
 * so this provider only owns the first call and the state around it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { api, describeError } from '@/src/api/client';
import { ErrorState } from '@/src/components/StateViews';
import { useTheme } from '@/src/theme';

export interface DeviceAuthState {
  /** True once the device is registered and requests can be signed. */
  ready: boolean;
  /** A readable sentence while the handshake is failing, otherwise null. */
  error: string | null;
  /** The server-issued device id. Show only the tail of it (shortDeviceId). */
  deviceId: string | null;
  /** Runs the handshake again. Safe to call while one is already in flight. */
  retry: () => void;
}

const DeviceAuthContext = createContext<DeviceAuthState | null>(null);

/** The splash the user actually sees on a cold start. */
function Registering(): ReactElement {
  const { colors, fonts, fontSizes, space } = useTheme();

  return (
    <View style={[styles.centre, { backgroundColor: colors.bg }]}>
      <Text
        style={{
          color: colors.fg,
          fontFamily: fonts.headline,
          fontSize: fontSizes.xxl,
          letterSpacing: 0.5,
        }}
      >
        FinBit
      </Text>
      <ActivityIndicator color={colors.accent} style={{ marginTop: space.xl }} />
    </View>
  );
}

export function DeviceAuthProvider({ children }: { children: ReactNode }): ReactElement {
  const { colors } = useTheme();
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setError(null);
    void (async () => {
      try {
        const id = await api.ensureDevice();
        if (!cancelled) {
          setDeviceId(id);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(describeError(caught));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  const value = useMemo<DeviceAuthState>(
    () => ({ ready: deviceId !== null, error, deviceId, retry }),
    [deviceId, error, retry],
  );

  let body: ReactNode;
  if (deviceId !== null) {
    body = children;
  } else if (error !== null) {
    body = (
      <View style={[styles.centre, { backgroundColor: colors.bg }]}>
        <ErrorState title="Cannot start FinBit" message={error} onRetry={retry} />
      </View>
    );
  } else {
    body = <Registering />;
  }

  return <DeviceAuthContext.Provider value={value}>{body}</DeviceAuthContext.Provider>;
}

/**
 * Device state, for the Settings screen's support row. Screens do not need to
 * check `ready`: they only mount once it is true.
 */
export function useDeviceAuth(): DeviceAuthState {
  const value = useContext(DeviceAuthContext);
  if (value === null) {
    throw new Error('useDeviceAuth must be used inside DeviceAuthProvider.');
  }
  return value;
}

const styles = StyleSheet.create({
  centre: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
