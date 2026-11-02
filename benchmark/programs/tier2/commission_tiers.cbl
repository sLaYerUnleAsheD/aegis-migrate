      * SALES COMMISSION BY TIER TABLE (tier 2)
      * Record (12 bytes): REP-ID X(4) | SALES 9(6)V99
      * The FIRST tier whose limit is >= SALES applies. The table is
      * 1-based and is filled at start-up with MOVE statements.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMMCALC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SALES-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  SALES-FILE.
       01  SALES-REC.
           05 SR-ID          PIC X(4).
           05 SR-SALES       PIC 9(6)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  TIER-TABLE.
           05 TIER-ENTRY OCCURS 4 TIMES.
              10 TIER-LIMIT  PIC 9(6)V99.
              10 TIER-RATE   PIC 9V99.
       01  WS-IDX            PIC 9        VALUE 0.
       01  WS-TIER           PIC 9        VALUE 0.
       01  WS-COMM           PIC 9(6)V99  VALUE 0.
       01  WS-TOTAL          PIC 9(9)V99  VALUE 0.
       01  WS-COUNT          PIC 9(3)     VALUE 0.
       01  WS-SALES-ED       PIC ZZZ,ZZ9.99.
       01  WS-RATE-ED        PIC 9.99.
       01  WS-COMM-ED        PIC ZZZ,ZZ9.99.
       01  WS-TOTAL-ED       PIC ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM INIT-PARA
           OPEN INPUT SALES-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE SALES-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       INIT-PARA.
           MOVE 1000.00 TO TIER-LIMIT (1)
           MOVE 2.50 TO TIER-RATE (1)
           MOVE 5000.00 TO TIER-LIMIT (2)
           MOVE 4.00 TO TIER-RATE (2)
           MOVE 20000.00 TO TIER-LIMIT (3)
           MOVE 5.50 TO TIER-RATE (3)
           MOVE 999999.99 TO TIER-LIMIT (4)
           MOVE 7.25 TO TIER-RATE (4).

       READ-PARA.
           READ SALES-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           MOVE 0 TO WS-TIER
           PERFORM VARYING WS-IDX FROM 1 BY 1
                   UNTIL WS-IDX > 4 OR WS-TIER > 0
               IF SR-SALES <= TIER-LIMIT (WS-IDX)
                   MOVE WS-IDX TO WS-TIER
               END-IF
           END-PERFORM
           COMPUTE WS-COMM ROUNDED =
               SR-SALES * TIER-RATE (WS-TIER) / 100
           ADD WS-COMM TO WS-TOTAL
           ADD 1 TO WS-COUNT
           MOVE SR-SALES TO WS-SALES-ED
           MOVE TIER-RATE (WS-TIER) TO WS-RATE-ED
           MOVE WS-COMM TO WS-COMM-ED
           DISPLAY SR-ID " T" WS-TIER " " WS-SALES-ED " "
               WS-RATE-ED "% " WS-COMM-ED
           PERFORM READ-PARA.

       SUMMARY-PARA.
           MOVE WS-TOTAL TO WS-TOTAL-ED
           DISPLAY "REPS: " WS-COUNT " TOTAL: " WS-TOTAL-ED.