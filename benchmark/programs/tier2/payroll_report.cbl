      * PAYROLL REPORT WITH DEPARTMENT CONTROL BREAK (tier 2)
      * Record (17 bytes): EMP-ID X(5) | DEPT X(3) | HOURS 9(3)V9 |
      *                    RATE 9(3)V99
      * Hours over 40 are paid at 1.5x. A subtotal line is printed
      * whenever the department changes (input need not be sorted).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  EMP-FILE.
       01  EMP-REC.
           05 ER-ID          PIC X(5).
           05 ER-DEPT        PIC X(3).
           05 ER-HOURS       PIC 9(3)V9.
           05 ER-RATE        PIC 9(3)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-FIRST-FLAG     PIC X        VALUE "Y".
           88 FIRST-RECORD                VALUE "Y".
       01  WS-PREV-DEPT      PIC X(3)     VALUE SPACES.
       01  WS-REG-HOURS      PIC 9(3)V9   VALUE 0.
       01  WS-OT-HOURS       PIC 9(3)V9   VALUE 0.
       01  WS-GROSS          PIC 9(7)V99  VALUE 0.
       01  WS-DEPT-TOTAL     PIC 9(9)V99  VALUE 0.
       01  WS-DEPT-COUNT     PIC 9(3)     VALUE 0.
       01  WS-GRAND-TOTAL    PIC 9(11)V99 VALUE 0.
       01  WS-GRAND-COUNT    PIC 9(5)     VALUE 0.
       01  WS-HOURS-ED       PIC ZZ9.9.
       01  WS-RATE-ED        PIC ZZ9.99.
       01  WS-GROSS-ED       PIC Z,ZZZ,ZZ9.99.
       01  WS-DEPT-ED        PIC ZZZ,ZZZ,ZZ9.99.
       01  WS-GRAND-ED       PIC ZZ,ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT EMP-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           IF NOT FIRST-RECORD
               PERFORM DEPT-BREAK-PARA
           END-IF
           CLOSE EMP-FILE
           PERFORM GRAND-PARA
           STOP RUN.

       READ-PARA.
           READ EMP-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           IF FIRST-RECORD
               MOVE ER-DEPT TO WS-PREV-DEPT
               MOVE "N" TO WS-FIRST-FLAG
           ELSE
               IF ER-DEPT NOT = WS-PREV-DEPT
                   PERFORM DEPT-BREAK-PARA
                   MOVE ER-DEPT TO WS-PREV-DEPT
               END-IF
           END-IF
           PERFORM PAY-PARA
           PERFORM READ-PARA.

       PAY-PARA.
           EVALUATE TRUE
               WHEN ER-HOURS > 40
                   MOVE 40 TO WS-REG-HOURS
                   COMPUTE WS-OT-HOURS = ER-HOURS - 40
               WHEN OTHER
                   MOVE ER-HOURS TO WS-REG-HOURS
                   MOVE 0 TO WS-OT-HOURS
           END-EVALUATE
           COMPUTE WS-GROSS ROUNDED =
               WS-REG-HOURS * ER-RATE + WS-OT-HOURS * ER-RATE * 1.5
           ADD WS-GROSS TO WS-DEPT-TOTAL
           ADD 1 TO WS-DEPT-COUNT
           ADD WS-GROSS TO WS-GRAND-TOTAL
           ADD 1 TO WS-GRAND-COUNT
           MOVE ER-HOURS TO WS-HOURS-ED
           MOVE ER-RATE TO WS-RATE-ED
           MOVE WS-GROSS TO WS-GROSS-ED
           DISPLAY ER-ID " " ER-DEPT " " WS-HOURS-ED " " WS-RATE-ED
               " " WS-GROSS-ED.

       DEPT-BREAK-PARA.
           MOVE WS-DEPT-TOTAL TO WS-DEPT-ED
           DISPLAY "  DEPT " WS-PREV-DEPT " EMPLOYEES: " WS-DEPT-COUNT
               " TOTAL: " WS-DEPT-ED
           MOVE 0 TO WS-DEPT-TOTAL
           MOVE 0 TO WS-DEPT-COUNT.

       GRAND-PARA.
           MOVE WS-GRAND-TOTAL TO WS-GRAND-ED
           DISPLAY "GRAND TOTAL (" WS-GRAND-COUNT "): " WS-GRAND-ED.