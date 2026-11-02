      * COMPOUND INTEREST SCHEDULE (tier 2): rounding at EVERY step
      * Record (16 bytes): ACCT X(4) | PRIN 9(5)V99 | RATE 9(2)V99 |
      *                    YEARS 9
      * Each year the balance is rounded to cents before the next year
      * is computed, so rounding errors compound exactly as they do in
      * COBOL. One line per year, then the final balance.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTSCHED.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SCHED-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  SCHED-FILE.
       01  SCHED-REC.
           05 SC-ACCT        PIC X(4).
           05 SC-PRIN        PIC 9(5)V99.
           05 SC-RATE        PIC 9(2)V99.
           05 SC-YEARS       PIC 9(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-BAL            PIC 9(8)V99  VALUE 0.
       01  WS-YEAR           PIC 99       VALUE 0.
       01  WS-COUNT          PIC 99       VALUE 0.
       01  WS-BAL-ED         PIC ZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT SCHED-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE SCHED-FILE
           DISPLAY "SCHEDULES: " WS-COUNT
           STOP RUN.

       READ-PARA.
           READ SCHED-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           MOVE SC-PRIN TO WS-BAL
           PERFORM VARYING WS-YEAR FROM 1 BY 1
                   UNTIL WS-YEAR > SC-YEARS
               COMPUTE WS-BAL ROUNDED =
                   WS-BAL * (1 + SC-RATE / 100)
               MOVE WS-BAL TO WS-BAL-ED
               DISPLAY SC-ACCT " Y" WS-YEAR " " WS-BAL-ED
           END-PERFORM
           MOVE WS-BAL TO WS-BAL-ED
           DISPLAY SC-ACCT " FINAL " WS-BAL-ED
           ADD 1 TO WS-COUNT
           PERFORM READ-PARA.