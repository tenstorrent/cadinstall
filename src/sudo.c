// SPDX-License-Identifier: Apache-2.0 
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <fcntl.h>

#define MAX_COMMAND_LENGTH 4096
#define MAX_OUTPUT_LENGTH 4096
// im not sure if i like this strategy - it might be better practice to actually hardcode the list. need to chew on it some more
#define ALLOWED_COMMANDS_FILE "/tools_vendor/FOSS/cadinstall/latest/etc/allowed_commands"

int main(int argc, char *argv[]) {
    char *command;
    char *arguments[500];
    int i = 0;
    int noOfArgs = 0;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <command>\n", argv[0]);
        exit(1);
    }
 
    command = argv[1];

    for (i=1; i<argc; i++)
    {
        arguments[noOfArgs] = argv[i];
        noOfArgs++;
    }
    arguments[noOfArgs] = NULL;

    FILE *allowed_commands_file;
    char allowed_command[MAX_COMMAND_LENGTH];
    int allowed = 0;
   
    // Check if the allowed_commands file exists
    if (access(ALLOWED_COMMANDS_FILE, F_OK) == -1) {
        fprintf(stderr, "Allowed commands file does not exist: %s\n", ALLOWED_COMMANDS_FILE);
        exit(1);
    }
    allowed_commands_file = fopen(ALLOWED_COMMANDS_FILE, "r");
    if (allowed_commands_file == NULL) {
        perror("fopen");
        exit(1);
    }

    while (fgets(allowed_command, MAX_COMMAND_LENGTH, allowed_commands_file) != NULL) {  
        // remove the newline character
        allowed_command[strcspn(allowed_command, "\n")] = 0;

        // fprintf(stdout, "Checking command against:\n\t%s\n", allowed_command);
        if (strcmp(allowed_command, command) == 0) {
            allowed = 1;
            break;
        }

    }

    fclose(allowed_commands_file);

    if (!allowed) {
        fprintf(stderr, "Command not allowed to be run via this utility: %s\n",command);
        exit(1);
    }

    /*
     Now that we're done with all the pre-work, let's get to the good stuff
     First get the euid - ie, the owner of the binary that has the setuid bit defined.
     Without this bit of magic, anything that depends on "id" (such as ssh) will not see the correct
     user. Anything that uses euid will, but that's not good enough. we need to actually toggle the uid
     for those commands.
    */
    uid_t euid;
    euid = geteuid();
    setreuid(euid,euid);  // this is the magic to setting the uid
    execvp(command, arguments); // now that the uid is defined properly, actually make the system call

    return 0;
}


/*
 The program is compiled with the following command ...
 gcc -o ../bin/.sudo sudo.c

 The program should be owned by cadtools and have the setuid bit set ...
 sudo chown cadtools:vendor_tools ../bin/.sudo && sudo chmod 755 ../bin/.sudo && sudo chmod u+s ../bin/.sudo
*/
