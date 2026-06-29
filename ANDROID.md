# Android App

The Android project is in `android/`.

## Build

Open the `android` folder in Android Studio, let Gradle sync, then run the `app` configuration.

The project uses:

- Java
- Android Gradle Plugin 8.7.3
- No third-party app dependencies
- `dictionaryapi.dev` for online definitions

The workbook is packaged as an app asset:

```text
android/app/src/main/assets/organized_vocabulary_notes.xlsx
```

Wrong answers are saved inside the app's private storage as `wrong_answers.json`.
