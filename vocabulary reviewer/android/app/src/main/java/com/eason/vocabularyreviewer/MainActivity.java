package com.eason.vocabularyreviewer;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.InputSource;

import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

import javax.xml.parsers.DocumentBuilderFactory;

public class MainActivity extends Activity {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final ArrayList<QuizItem> allItems = new ArrayList<>();
    private final ArrayList<QuizItem> queue = new ArrayList<>();
    private final Random random = new Random();

    private LinearLayout root;
    private TextView title;
    private TextView stats;
    private TextView questionType;
    private TextView prompt;
    private TextView meta;
    private LinearLayout answerArea;
    private TextView feedback;
    private Button nextButton;
    private Spinner categorySpinner;
    private Button allModeButton;
    private Button choicesModeButton;
    private Button formsModeButton;

    private String mode = "all";
    private String category = "All categories";
    private int index = 0;
    private int seen = 0;
    private int correct = 0;
    private int wrong = 0;
    private boolean answered = false;
    private Definition currentDefinition;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildLayout();
        loadItems();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void buildLayout() {
        ScrollView scroll = new ScrollView(this);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(18), dp(18), dp(18));
        root.setBackgroundColor(Color.rgb(247, 248, 245));
        scroll.addView(root);

        title = text("Vocabulary Reviewer", 26, true);
        root.addView(title);

        stats = text("", 14, false);
        stats.setTextColor(Color.rgb(91, 105, 100));
        stats.setPadding(0, dp(10), 0, dp(12));
        root.addView(stats);

        categorySpinner = new Spinner(this);
        root.addView(categorySpinner, matchWrap());

        LinearLayout modes = new LinearLayout(this);
        modes.setOrientation(LinearLayout.HORIZONTAL);
        modes.setPadding(0, dp(12), 0, dp(12));
        allModeButton = smallButton("All");
        choicesModeButton = smallButton("Choices");
        formsModeButton = smallButton("Forms");
        modes.addView(allModeButton, weightWrap());
        modes.addView(choicesModeButton, weightWrap());
        modes.addView(formsModeButton, weightWrap());
        root.addView(modes);

        questionType = text("", 13, true);
        questionType.setTextColor(Color.rgb(155, 102, 25));
        root.addView(questionType);

        prompt = text("Loading workbook...", 24, true);
        prompt.setPadding(0, dp(8), 0, dp(12));
        root.addView(prompt);

        meta = text("", 14, false);
        meta.setTextColor(Color.rgb(91, 105, 100));
        root.addView(meta);

        answerArea = new LinearLayout(this);
        answerArea.setOrientation(LinearLayout.VERTICAL);
        answerArea.setPadding(0, dp(18), 0, dp(10));
        root.addView(answerArea);

        feedback = text("", 16, false);
        feedback.setPadding(dp(12), dp(12), dp(12), dp(12));
        feedback.setVisibility(View.GONE);
        root.addView(feedback, matchWrap());

        nextButton = button("Next");
        nextButton.setEnabled(false);
        nextButton.setOnClickListener(v -> nextQuestion());
        root.addView(nextButton, matchWrap());

        allModeButton.setOnClickListener(v -> setMode("all"));
        choicesModeButton.setOnClickListener(v -> setMode("multiple_choice"));
        formsModeButton.setOnClickListener(v -> setMode("word_form"));

        setContentView(scroll);
    }

    private void loadItems() {
        executor.execute(() -> {
            try {
                List<VocabRow> rows = XlsxLoader.load(getAssets(), "organized_vocabulary_notes.xlsx");
                List<QuizItem> built = QuizBuilder.build(rows);
                runOnUiThread(() -> {
                    allItems.clear();
                    allItems.addAll(built);
                    setupCategories();
                    rebuildQueue();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> prompt.setText("Could not load workbook: " + ex.getMessage()));
            }
        });
    }

    private void setupCategories() {
        ArrayList<String> categories = new ArrayList<>();
        categories.add("All categories");
        Set<String> seenCategories = new HashSet<>();
        for (QuizItem item : allItems) {
            if (item.category.length() > 0 && seenCategories.add(item.category)) {
                categories.add(item.category);
            }
        }
        Collections.sort(categories.subList(1, categories.size()));
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, categories);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        categorySpinner.setAdapter(adapter);
        categorySpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                category = categories.get(position);
                rebuildQueue();
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
    }

    private void setMode(String newMode) {
        mode = newMode;
        rebuildQueue();
    }

    private void rebuildQueue() {
        queue.clear();
        for (QuizItem item : allItems) {
            if (!"All categories".equals(category) && !category.equals(item.category)) {
                continue;
            }
            if (!"all".equals(mode) && !mode.equals(item.type)) {
                continue;
            }
            queue.add(item);
        }
        Collections.shuffle(queue, random);
        index = 0;
        renderCurrent();
    }

    private void renderCurrent() {
        answered = false;
        currentDefinition = null;
        nextButton.setEnabled(false);
        feedback.setVisibility(View.GONE);
        answerArea.removeAllViews();
        updateStats();

        if (queue.isEmpty() || index >= queue.size()) {
            questionType.setText("");
            prompt.setText("Session complete.");
            meta.setText("");
            return;
        }

        QuizItem item = queue.get(index);
        if ("multiple_choice".equals(item.type)) {
            renderMultipleChoice(item);
        } else {
            renderWordForm(item);
        }
    }

    private void renderMultipleChoice(QuizItem item) {
        questionType.setText("DEFINITION");
        prompt.setText("Looking up definition...");
        meta.setText(item.category + " / " + item.pos + " / row " + item.row);
        for (String choice : item.choices) {
            Button choiceButton = button(choice);
            choiceButton.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
            choiceButton.setOnClickListener(v -> answerMultipleChoice(item, choice));
            answerArea.addView(choiceButton, matchWrap());
        }

        executor.execute(() -> {
            Definition definition = DictionaryClient.lookup(this, item);
            runOnUiThread(() -> {
                currentDefinition = definition;
                prompt.setText(definition.text);
                meta.setText(item.category + " / " + item.pos + " / " + definition.source + " / row " + item.row);
            });
        });
    }

    private void renderWordForm(QuizItem item) {
        questionType.setText("WORD FORM");
        prompt.setText("Convert \"" + item.sourceWord + "\" to " + item.targetPos + ".");
        meta.setText(item.category + " / " + item.sourcePos + " / row " + item.row);

        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        answerArea.addView(input, matchWrap());

        Button check = button("Check");
        check.setOnClickListener(v -> answerForm(item, input.getText().toString(), input, check));
        answerArea.addView(check, matchWrap());
        input.requestFocus();
    }

    private void answerMultipleChoice(QuizItem item, String choice) {
        if (answered) {
            return;
        }
        boolean isCorrect = normalize(choice).equals(normalize(item.displayWord));
        for (int i = 0; i < answerArea.getChildCount(); i++) {
            View child = answerArea.getChildAt(i);
            child.setEnabled(false);
        }
        finishAnswer(item, choice, item.displayWord, isCorrect);
    }

    private void answerForm(QuizItem item, String value, EditText input, Button check) {
        if (answered) {
            return;
        }
        boolean isCorrect = false;
        for (String accepted : item.acceptedAnswers) {
            if (normalize(value).equals(normalize(accepted))) {
                isCorrect = true;
                break;
            }
        }
        input.setEnabled(false);
        check.setEnabled(false);
        finishAnswer(item, value, item.answer, isCorrect);
    }

    private void finishAnswer(QuizItem item, String userAnswer, String correctAnswer, boolean isCorrect) {
        answered = true;
        seen += 1;
        if (isCorrect) {
            correct += 1;
        } else {
            wrong += 1;
            WrongAnswerStore.save(this, item, userAnswer, correctAnswer, currentDefinition);
        }
        updateStats();
        nextButton.setEnabled(true);

        StringBuilder message = new StringBuilder();
        message.append(isCorrect ? "Correct" : "Incorrect");
        message.append("\nCorrect answer: ").append(correctAnswer);
        if ("multiple_choice".equals(item.type)) {
            message.append("\nChoices: ");
            for (int i = 0; i < item.choices.size(); i++) {
                if (i > 0) {
                    message.append(", ");
                }
                message.append(item.choices.get(i));
            }
        }
        feedback.setText(message.toString());
        feedback.setBackgroundColor(isCorrect ? Color.rgb(233, 247, 239) : Color.rgb(255, 240, 239));
        feedback.setVisibility(View.VISIBLE);
    }

    private void nextQuestion() {
        index += 1;
        renderCurrent();
    }

    private void updateStats() {
        int total = queue.size();
        int current = total == 0 ? 0 : Math.min(index + 1, total);
        stats.setText("Seen " + seen + "   Correct " + correct + "   Wrong " + wrong + "   " + current + " / " + total);
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US).replaceAll("\\s+", " ");
    }

    private TextView text(String value, int sp, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(Color.rgb(22, 32, 29));
        if (bold) {
            view.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        }
        return view;
    }

    private Button button(String value) {
        Button view = new Button(this);
        view.setText(value);
        view.setAllCaps(false);
        view.setMinHeight(dp(48));
        return view;
    }

    private Button smallButton(String value) {
        Button view = button(value);
        view.setTextSize(13);
        return view;
    }

    private LinearLayout.LayoutParams matchWrap() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(0, dp(6), 0, dp(6));
        return params;
    }

    private LinearLayout.LayoutParams weightWrap() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        params.setMargins(dp(2), 0, dp(2), 0);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    static class VocabRow {
        final String sourceSheet;
        final int row;
        final String category;
        final String word;
        final String pos;
        final String chinese;
        final String note;

        VocabRow(String sourceSheet, int row, String category, String word, String pos, String chinese, String note) {
            this.sourceSheet = sourceSheet;
            this.row = row;
            this.category = category;
            this.word = word;
            this.pos = pos;
            this.chinese = chinese;
            this.note = note;
        }
    }

    static class QuizItem {
        String id;
        String type;
        String sourceSheet;
        int row;
        String category;
        String word;
        String displayWord;
        String lookupWord;
        String pos;
        String meaning;
        String note;
        int senseIndex;
        ArrayList<String> acceptedAnswers = new ArrayList<>();
        ArrayList<String> choices = new ArrayList<>();
        String sourceWord;
        String sourcePos;
        String targetPos;
        String answer;
    }

    static class Definition {
        final String text;
        final String source;

        Definition(String text, String source) {
            this.text = text;
            this.source = source;
        }
    }

    static class XlsxLoader {
        static List<VocabRow> load(AssetManager assets, String assetName) throws Exception {
            Map<String, byte[]> files = unzip(assets.open(assetName));
            List<String> shared = readSharedStrings(files.get("xl/sharedStrings.xml"));
            Document workbook = parseXml(files.get("xl/workbook.xml"));
            Document rels = parseXml(files.get("xl/_rels/workbook.xml.rels"));
            Map<String, String> ridToTarget = workbookRels(rels);

            ArrayList<VocabRow> rows = new ArrayList<>();
            NodeList sheetNodes = workbook.getElementsByTagNameNS("*", "sheet");
            for (int i = 0; i < sheetNodes.getLength(); i++) {
                Element sheet = (Element) sheetNodes.item(i);
                String title = sheet.getAttribute("name");
                String lowerTitle = title.toLowerCase(Locale.US);
                if (lowerTitle.contains("review") || lowerTitle.contains("summary")) {
                    continue;
                }
                String rid = sheet.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id");
                String path = resolveTarget(ridToTarget.get(rid));
                List<RowData> sheetRows = readSheet(files.get(path), shared);
                if (sheetRows.isEmpty() || !isVocabularyHeader(sheetRows.get(0).values)) {
                    continue;
                }
                for (int r = 1; r < sheetRows.size(); r++) {
                    RowData data = sheetRows.get(r);
                    String word = value(data.values, 2);
                    if (word.length() == 0) {
                        continue;
                    }
                    rows.add(new VocabRow(
                            title,
                            data.rowNumber,
                            value(data.values, 1),
                            word,
                            value(data.values, 3),
                            value(data.values, 4),
                            value(data.values, 5)
                    ));
                }
            }
            return rows;
        }

        private static Map<String, byte[]> unzip(InputStream input) throws Exception {
            Map<String, byte[]> files = new HashMap<>();
            ZipInputStream zip = new ZipInputStream(input);
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] buffer = new byte[4096];
                int read;
                while ((read = zip.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                }
                files.put(entry.getName(), out.toByteArray());
            }
            return files;
        }

        private static List<String> readSharedStrings(byte[] xml) throws Exception {
            ArrayList<String> strings = new ArrayList<>();
            if (xml == null) {
                return strings;
            }
            Document doc = parseXml(xml);
            NodeList items = doc.getElementsByTagNameNS("*", "si");
            for (int i = 0; i < items.getLength(); i++) {
                strings.add(items.item(i).getTextContent());
            }
            return strings;
        }

        private static Map<String, String> workbookRels(Document rels) {
            Map<String, String> map = new HashMap<>();
            NodeList nodes = rels.getElementsByTagName("Relationship");
            for (int i = 0; i < nodes.getLength(); i++) {
                Element rel = (Element) nodes.item(i);
                map.put(rel.getAttribute("Id"), rel.getAttribute("Target"));
            }
            return map;
        }

        private static List<RowData> readSheet(byte[] xml, List<String> shared) throws Exception {
            ArrayList<RowData> rows = new ArrayList<>();
            Document doc = parseXml(xml);
            NodeList rowNodes = doc.getElementsByTagNameNS("*", "row");
            for (int i = 0; i < rowNodes.getLength(); i++) {
                Element row = (Element) rowNodes.item(i);
                int rowNum = parseInt(row.getAttribute("r"), i + 1);
                Map<Integer, String> values = new HashMap<>();
                NodeList cells = row.getElementsByTagNameNS("*", "c");
                for (int c = 0; c < cells.getLength(); c++) {
                    Element cell = (Element) cells.item(c);
                    int col = colToIndex(cell.getAttribute("r"));
                    String type = cell.getAttribute("t");
                    String value = "";
                    if ("inlineStr".equals(type)) {
                        value = cell.getTextContent();
                    } else {
                        Node v = firstByLocalName(cell, "v");
                        if (v != null) {
                            value = v.getTextContent();
                            if ("s".equals(type)) {
                                int index = parseInt(value, -1);
                                value = index >= 0 && index < shared.size() ? shared.get(index) : value;
                            }
                        }
                    }
                    value = value == null ? "" : value.trim();
                    if (col > 0 && value.length() > 0) {
                        values.put(col, value);
                    }
                }
                if (!values.isEmpty()) {
                    rows.add(new RowData(rowNum, values));
                }
            }
            return rows;
        }

        private static Document parseXml(byte[] xml) throws Exception {
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            factory.setNamespaceAware(true);
            return factory.newDocumentBuilder().parse(new InputSource(new ByteArrayInputStream(xml)));
        }

        private static String resolveTarget(String target) {
            if (target == null) {
                return "";
            }
            target = target.startsWith("/") ? target.substring(1) : target;
            return target.startsWith("xl/") ? target : "xl/" + target;
        }

        private static boolean isVocabularyHeader(Map<Integer, String> values) {
            return "word / phrase".equalsIgnoreCase(value(values, 2))
                    && "chinese meaning".equalsIgnoreCase(value(values, 4));
        }

        private static Node firstByLocalName(Element parent, String localName) {
            NodeList nodes = parent.getElementsByTagNameNS("*", localName);
            return nodes.getLength() == 0 ? null : nodes.item(0);
        }

        private static String value(Map<Integer, String> values, int key) {
            String value = values.get(key);
            return value == null ? "" : value.trim();
        }

        private static int colToIndex(String ref) {
            int result = 0;
            for (int i = 0; i < ref.length(); i++) {
                char ch = ref.charAt(i);
                if (ch < 'A' || ch > 'Z') {
                    break;
                }
                result = result * 26 + (ch - 'A' + 1);
            }
            return result;
        }

        private static int parseInt(String value, int fallback) {
            try {
                return Integer.parseInt(value);
            } catch (Exception ex) {
                return fallback;
            }
        }

        static class RowData {
            final int rowNumber;
            final Map<Integer, String> values;

            RowData(int rowNumber, Map<Integer, String> values) {
                this.rowNumber = rowNumber;
                this.values = values;
            }
        }
    }

    static class QuizBuilder {
        private static final Pattern NOTE_FORM = Pattern.compile("\\b(plural|noun|verb|adjective|adverb)\\s*:\\s*([A-Za-z][A-Za-z -]*)", Pattern.CASE_INSENSITIVE);

        static List<QuizItem> build(List<VocabRow> rows) {
            ArrayList<QuizItem> items = new ArrayList<>();
            for (VocabRow row : rows) {
                String[] senses = splitSenses(row.chinese);
                for (int i = 0; i < senses.length; i++) {
                    QuizItem item = new QuizItem();
                    item.id = "mc-" + row.sourceSheet + "-" + row.row + "-" + i;
                    item.type = "multiple_choice";
                    item.sourceSheet = row.sourceSheet;
                    item.row = row.row;
                    item.category = row.category;
                    item.word = row.word;
                    item.displayWord = row.word;
                    item.lookupWord = lookupWord(row.word);
                    item.pos = row.pos;
                    item.meaning = senses[i];
                    item.note = row.note;
                    item.senseIndex = i;
                    Collections.addAll(item.acceptedAnswers, splitVariants(row.word));
                    items.add(item);
                }
            }
            addChoices(items);
            items.addAll(formQuestions(rows));
            return items;
        }

        private static void addChoices(ArrayList<QuizItem> items) {
            for (QuizItem item : items) {
                ArrayList<QuizItem> candidates = new ArrayList<>();
                for (QuizItem candidate : items) {
                    if (candidate == item || candidate.displayWord.equalsIgnoreCase(item.displayWord)) {
                        continue;
                    }
                    candidates.add(candidate);
                }
                Collections.sort(candidates, Comparator.comparingDouble(c -> -choiceScore(item, c)));
                ArrayList<String> choices = new ArrayList<>();
                choices.add(item.displayWord);
                for (QuizItem candidate : candidates) {
                    if (choices.size() == 5) {
                        break;
                    }
                    if (sameCategoryOrPos(item, candidate) && !containsIgnoreCase(choices, candidate.displayWord)) {
                        choices.add(candidate.displayWord);
                    }
                }
                for (QuizItem candidate : candidates) {
                    if (choices.size() == 5) {
                        break;
                    }
                    if (!containsIgnoreCase(choices, candidate.displayWord)) {
                        choices.add(candidate.displayWord);
                    }
                }
                Collections.shuffle(choices, new Random(item.id.hashCode()));
                item.choices = choices;
            }
        }

        private static List<QuizItem> formQuestions(List<VocabRow> rows) {
            LinkedHashMap<String, QuizItem> map = new LinkedHashMap<>();
            for (VocabRow row : rows) {
                Matcher matcher = NOTE_FORM.matcher(row.note == null ? "" : row.note);
                while (matcher.find()) {
                    String answer = matcher.group(2).trim().split("/")[0].trim();
                    if (answer.length() > 0 && !answer.equalsIgnoreCase(row.word)) {
                        QuizItem item = formItem(row, lookupWord(row.word), row.pos, matcher.group(1).toLowerCase(Locale.US), answer);
                        map.put(item.id, item);
                    }
                }
                String[] variants = splitVariants(row.word);
                if (variants.length > 1) {
                    for (int i = 1; i < variants.length; i++) {
                        String target = variants[i];
                        String targetPos = target.endsWith("s") || target.endsWith("i") ? "plural" : "related form";
                        QuizItem item = formItem(row, variants[0], row.pos, targetPos, target);
                        map.put(item.id, item);
                    }
                }
            }
            return new ArrayList<>(map.values());
        }

        private static QuizItem formItem(VocabRow row, String sourceWord, String sourcePos, String targetPos, String answer) {
            QuizItem item = new QuizItem();
            item.id = "form-" + row.sourceSheet + "-" + row.row + "-" + sourceWord + "-" + targetPos + "-" + answer;
            item.type = "word_form";
            item.sourceSheet = row.sourceSheet;
            item.row = row.row;
            item.category = row.category;
            item.sourceWord = sourceWord;
            item.sourcePos = sourcePos;
            item.targetPos = targetPos;
            item.answer = answer;
            item.meaning = row.chinese;
            item.note = row.note;
            item.acceptedAnswers.add(answer);
            return item;
        }

        private static String[] splitSenses(String chinese) {
            String[] raw = chinese == null ? new String[]{""} : chinese.split("[;；]");
            ArrayList<String> parts = new ArrayList<>();
            for (String part : raw) {
                part = part.trim();
                if (part.length() > 0) {
                    parts.add(part);
                }
            }
            return parts.isEmpty() ? new String[]{""} : parts.toArray(new String[0]);
        }

        private static String[] splitVariants(String word) {
            String[] raw = word == null ? new String[]{""} : word.split("\\s+/\\s+");
            ArrayList<String> parts = new ArrayList<>();
            for (String part : raw) {
                part = part.trim();
                if (part.length() > 0) {
                    parts.add(part);
                }
            }
            return parts.isEmpty() ? new String[]{word} : parts.toArray(new String[0]);
        }

        private static String lookupWord(String word) {
            String first = splitVariants(word)[0];
            return first.replaceAll("\\([^)]*\\)", "").trim();
        }

        private static boolean sameCategoryOrPos(QuizItem a, QuizItem b) {
            return a.category.equals(b.category) || a.pos.equals(b.pos);
        }

        private static double choiceScore(QuizItem a, QuizItem b) {
            double score = similarity(a.displayWord, b.displayWord);
            if (a.category.equals(b.category)) {
                score += 0.35;
            }
            if (a.pos.equals(b.pos)) {
                score += 0.25;
            }
            return score;
        }

        private static double similarity(String a, String b) {
            a = a.toLowerCase(Locale.US);
            b = b.toLowerCase(Locale.US);
            int common = 0;
            for (int i = 0; i < Math.min(a.length(), b.length()); i++) {
                if (a.charAt(i) != b.charAt(i)) {
                    break;
                }
                common++;
            }
            int shared = 0;
            for (int i = 0; i < a.length(); i++) {
                if (b.indexOf(a.charAt(i)) >= 0) {
                    shared++;
                }
            }
            return (shared / (double) Math.max(1, Math.max(a.length(), b.length()))) + (common / 20.0);
        }

        private static boolean containsIgnoreCase(List<String> values, String value) {
            for (String existing : values) {
                if (existing.equalsIgnoreCase(value)) {
                    return true;
                }
            }
            return false;
        }
    }

    static class DictionaryClient {
        static Definition lookup(Context context, QuizItem item) {
            SharedPreferences prefs = context.getSharedPreferences("definitions", Context.MODE_PRIVATE);
            String cacheKey = item.lookupWord.toLowerCase(Locale.US) + "|" + item.pos + "|" + item.senseIndex;
            String cached = prefs.getString(cacheKey, null);
            if (cached != null) {
                return new Definition(cached, "dictionary cache");
            }
            try {
                String encoded = URLEncoder.encode(item.lookupWord, "UTF-8").replace("+", "%20");
                URL url = new URL("https://api.dictionaryapi.dev/api/v2/entries/en/" + encoded);
                HttpURLConnection connection = (HttpURLConnection) url.openConnection();
                connection.setConnectTimeout(8000);
                connection.setReadTimeout(8000);
                connection.setRequestProperty("User-Agent", "vocabulary-reviewer-android/1.0");
                if (connection.getResponseCode() >= 200 && connection.getResponseCode() < 300) {
                    String body = readAll(connection.getInputStream());
                    String definition = extractDefinition(body, item);
                    if (definition.length() > 0) {
                        prefs.edit().putString(cacheKey, definition).apply();
                        return new Definition(definition, "dictionary");
                    }
                }
            } catch (Exception ignored) {
            }
            if (item.note != null && item.note.length() > 0 && !Pattern.compile("[\\u4e00-\\u9fff]").matcher(item.note).find()) {
                return new Definition(item.note, "workbook note");
            }
            return new Definition("Workbook meaning: " + item.meaning, "workbook fallback");
        }

        private static String extractDefinition(String body, QuizItem item) throws Exception {
            JSONArray entries = new JSONArray(body);
            ArrayList<String> definitions = new ArrayList<>();
            ArrayList<String> matched = new ArrayList<>();
            for (int i = 0; i < entries.length(); i++) {
                JSONObject entry = entries.getJSONObject(i);
                JSONArray meanings = entry.optJSONArray("meanings");
                if (meanings == null) {
                    continue;
                }
                for (int m = 0; m < meanings.length(); m++) {
                    JSONObject meaning = meanings.getJSONObject(m);
                    String part = meaning.optString("partOfSpeech", "");
                    JSONArray defs = meaning.optJSONArray("definitions");
                    if (defs == null) {
                        continue;
                    }
                    for (int d = 0; d < defs.length(); d++) {
                        String definition = defs.getJSONObject(d).optString("definition", "").trim();
                        if (definition.length() == 0) {
                            continue;
                        }
                        definitions.add(definition);
                        if (matchesPos(item.pos, part)) {
                            matched.add(definition);
                        }
                    }
                }
            }
            ArrayList<String> pool = matched.isEmpty() ? definitions : matched;
            if (pool.isEmpty()) {
                return "";
            }
            return pool.get(Math.min(item.senseIndex, pool.size() - 1));
        }

        private static boolean matchesPos(String rowPos, String dictionaryPos) {
            rowPos = rowPos.toLowerCase(Locale.US);
            dictionaryPos = dictionaryPos.toLowerCase(Locale.US);
            return rowPos.contains("n.") && dictionaryPos.equals("noun")
                    || rowPos.contains("v.") && dictionaryPos.equals("verb")
                    || rowPos.contains("adj") && dictionaryPos.equals("adjective")
                    || rowPos.contains("adv") && dictionaryPos.equals("adverb");
        }

        private static String readAll(InputStream stream) throws Exception {
            BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                out.append(line);
            }
            return out.toString();
        }
    }

    static class WrongAnswerStore {
        static void save(Context context, QuizItem item, String userAnswer, String correctAnswer, Definition definition) {
            try {
                File file = new File(context.getFilesDir(), "wrong_answers.json");
                JSONArray array;
                if (file.exists()) {
                    byte[] bytes = readBytes(file);
                    array = new JSONArray(new String(bytes, StandardCharsets.UTF_8));
                } else {
                    array = new JSONArray();
                }
                JSONObject object = new JSONObject();
                object.put("saved_at", System.currentTimeMillis());
                object.put("type", item.type);
                object.put("row", item.row);
                object.put("category", item.category);
                object.put("word", item.displayWord != null ? item.displayWord : item.sourceWord);
                object.put("user_answer", userAnswer);
                object.put("correct_answer", correctAnswer);
                object.put("definition", definition == null ? "" : definition.text);
                array.put(object);
                FileOutputStream out = new FileOutputStream(file);
                out.write(array.toString(2).getBytes(StandardCharsets.UTF_8));
                out.close();
            } catch (Exception ignored) {
            }
        }

        private static byte[] readBytes(File file) throws Exception {
            FileInputStream input = new FileInputStream(file);
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int read;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
            }
            input.close();
            return output.toByteArray();
        }
    }
}
