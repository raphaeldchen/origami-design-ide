/*
 * OrieditaValidator — headless flat-foldability checker for the Origami IDE linter.
 *
 * Oriedita ships only a Swing GUI (App.java); there is no validation CLI. This
 * thin wrapper drives Oriedita's real per-vertex flat-foldability engine
 * headlessly so the Python MCP server (linter_server.py) can shell out to it.
 *
 * Pipeline (all verified against oriedita/oriedita @ v1.1.3):
 *   FoldImporter.importFile(file) -> Save        // parses .fold via fold.io
 *   new FoldLineSet().setSave(save)              // loads creases
 *   Check4.apply(fls)                            // Maekawa/Kawasaki/#folds/BLB
 *   fls.getViolations()                          // queue of FlatFoldabilityViolation
 *
 * Output protocol (stdout, tab-delimited; Python formats for the agent):
 *   PASS                                         flat-foldable, no violations
 *   VIOLATION\t<rule>\t<color>\t<x>\t<y>         one line per violating vertex
 * On any failure (not a FOLD file, parse error, engine error):
 *   ERROR\t<message>   -> stderr, exit code 1
 *
 * Compile/run: see build_linter.sh (compiles against oriedita-<ver>.jar).
 */

import java.io.File;
import java.util.Queue;

import origami.crease_pattern.FlatFoldabilityViolation;
import origami.crease_pattern.FoldLineSet;
import origami.crease_pattern.element.Point;
import origami.crease_pattern.worker.foldlineset.Check4;
import oriedita.editor.export.FoldImporter;
import oriedita.editor.save.Save;

public class OrieditaValidator {

    public static void main(String[] args) {
        if (args.length != 1) {
            System.err.println("ERROR\tusage: OrieditaValidator <path-to.fold>");
            System.exit(1);
            return;
        }

        File foldFile = new File(args[0]);
        if (!foldFile.isFile()) {
            System.err.println("ERROR\tno such file: " + args[0]);
            System.exit(1);
            return;
        }

        try {
            // 1. Parse the .fold into Oriedita's internal crease representation.
            Save save = new FoldImporter().importFile(foldFile);

            // 2. Load it into a FoldLineSet (Save extends LineSegmentSave).
            FoldLineSet fls = new FoldLineSet();
            fls.setSave(save);

            // 3. Run the real flat-foldability check (populates the violation queue).
            Check4.apply(fls);

            // 4. Report.
            Queue<FlatFoldabilityViolation> violations = fls.getViolations();
            if (violations.isEmpty()) {
                System.out.println("PASS");
            } else {
                StringBuilder sb = new StringBuilder();
                for (FlatFoldabilityViolation v : violations) {
                    Point p = v.getPoint();
                    sb.append("VIOLATION")
                      .append('\t').append(v.getViolatedRule())
                      .append('\t').append(v.getColor())
                      .append('\t').append(p.getX())
                      .append('\t').append(p.getY())
                      .append('\n');
                }
                // Single write to keep lines intact.
                System.out.print(sb);
            }
            System.exit(0);
        } catch (Throwable t) {
            // Any failure — malformed FOLD, JSON that isn't FOLD, engine fault —
            // is surfaced as a clean ERROR line. Throwable (not Exception) so even
            // an unexpected error/assertion becomes a parseable result, not a stack
            // dump the Python side would misread.
            String msg = t.getMessage();
            if (msg == null) {
                msg = t.getClass().getSimpleName();
            }
            System.err.println("ERROR\t" + msg.replace('\n', ' ').replace('\t', ' '));
            System.exit(1);
        }
    }
}
