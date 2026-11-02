      * DATE VALIDATION WITH LEAP YEARS (tier 3)
      * Record (12 bytes): ID X(4) | YYYY 9(4) | MM 9(2) | DD 9(2)
      * Leap year: divisible by 4, except centuries unless divisible
      * by 400. Checks month first, then day against the month length.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATECHK.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT DATE-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  DATE-FILE.
       01  DATE-REC.
           05 DT-ID          PIC X(4).
           05 DT-YYYY        PIC 9(4).
           05 DT-MM          PIC 9(2).
           05 DT-DD          PIC 9(2).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-LEAP-FLAG      PIC X        VALUE "N".
           88 IS-LEAP                     VALUE "Y".
       01  WS-Q              PIC 9(4)     VALUE 0.
       01  WS-R4             PIC 9(3)     VALUE 0.
       01  WS-R100           PIC 9(3)     VALUE 0.
       01  WS-R400           PIC 9(3)     VALUE 0.
       01  WS-MAX-DAY        PIC 99       VALUE 0.
       01  WS-VALID          PIC 99       VALUE 0.
       01  WS-BAD-MONTH      PIC 99       VALUE 0.
       01  WS-BAD-DAY        PIC 99       VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT DATE-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE DATE-FILE
           DISPLAY "VALID: " WS-VALID " BAD MONTH: " WS-BAD-MONTH
               " BAD DAY: " WS-BAD-DAY
           STOP RUN.

       READ-PARA.
           READ DATE-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           PERFORM LEAP-PARA
           EVALUATE TRUE
               WHEN DT-MM < 1 OR DT-MM > 12
                   ADD 1 TO WS-BAD-MONTH
                   DISPLAY DT-ID " BAD MONTH " DT-MM
               WHEN OTHER
                   PERFORM DAYS-PARA
                   IF DT-DD < 1 OR DT-DD > WS-MAX-DAY
                       ADD 1 TO WS-BAD-DAY
                       DISPLAY DT-ID " BAD DAY " DT-DD
                           " MAX " WS-MAX-DAY
                   ELSE
                       ADD 1 TO WS-VALID
                       DISPLAY DT-ID " VALID " DT-YYYY "-" DT-MM
                           "-" DT-DD
                   END-IF
           END-EVALUATE
           PERFORM READ-PARA.

       LEAP-PARA.
           DIVIDE DT-YYYY BY 4 GIVING WS-Q REMAINDER WS-R4
           DIVIDE DT-YYYY BY 100 GIVING WS-Q REMAINDER WS-R100
           DIVIDE DT-YYYY BY 400 GIVING WS-Q REMAINDER WS-R400
           IF WS-R4 = 0 AND (WS-R100 NOT = 0 OR WS-R400 = 0)
               MOVE "Y" TO WS-LEAP-FLAG
           ELSE
               MOVE "N" TO WS-LEAP-FLAG
           END-IF.

       DAYS-PARA.
           EVALUATE DT-MM
               WHEN 2
                   IF IS-LEAP
                       MOVE 29 TO WS-MAX-DAY
                   ELSE
                       MOVE 28 TO WS-MAX-DAY
                   END-IF
               WHEN 4
               WHEN 6
               WHEN 9
               WHEN 11
                   MOVE 30 TO WS-MAX-DAY
               WHEN OTHER
                   MOVE 31 TO WS-MAX-DAY
           END-EVALUATE.