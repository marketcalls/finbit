module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    // react-native-worklets powers reanimated 4 and must stay last.
    plugins: ['react-native-worklets/plugin'],
  };
};
